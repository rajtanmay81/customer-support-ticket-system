from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_staff
from app import schemas
from app.models import (
    Ticket, Comment, Category, Priority, User, UserRole, TicketStatus, TicketRating,
    AssignmentSource, TicketHandlingMode,
)
from app.services import (
    ml_service, sla as sla_service, genai_service, rag_service, assignment_service,
    ai_triage_service, ml_feedback_service,
)
from app.services.ticket_access import (
    agent_access_filter, assert_can_view, assert_can_write, get_ticket_or_404, record_agent_access,
)
from app.ws_manager import manager

router = APIRouter(prefix="/tickets", tags=["tickets"])


# ---------- helpers ----------

def _to_attachment_out(attachment) -> schemas.AttachmentOut:
    return schemas.AttachmentOut(
        id=attachment.id,
        ticket_id=attachment.ticket_id,
        comment_id=attachment.comment_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        uploaded_by_id=attachment.uploaded_by_id,
        uploaded_by_name=attachment.uploaded_by.name,
        created_at=attachment.created_at,
    )


def _to_comment_out(comment: Comment) -> schemas.CommentOut:
    return schemas.CommentOut(
        id=comment.id,
        ticket_id=comment.ticket_id,
        author_id=comment.author_id,
        author_name=comment.author.name,
        body=comment.body,
        is_internal_note=comment.is_internal_note,
        is_ai_generated=comment.is_ai_generated,
        sentiment=comment.sentiment,
        created_at=comment.created_at,
        attachments=[_to_attachment_out(a) for a in comment.attachments],
    )


def _to_sla_out(ticket: Ticket) -> Optional[schemas.SLAOut]:
    if ticket.sla_history is None:
        return None
    sla = sla_service.refresh_breach_flags(ticket.sla_history)
    return schemas.SLAOut.model_validate(sla)


def _to_ticket_out(ticket: Ticket, include_comments: bool = False, current_user: Optional[User] = None):
    data = dict(
        id=ticket.id,
        subject=ticket.subject,
        description=ticket.description,
        status=ticket.status,
        customer_id=ticket.customer_id,
        customer_name=ticket.customer.name,
        assigned_agent_id=ticket.assigned_agent_id,
        assigned_agent_name=ticket.assigned_agent.name if ticket.assigned_agent else None,
        assignment_source=ticket.assignment_source,
        assignment_note=ticket.assignment_note,
        handling_mode=ticket.handling_mode,
        dissatisfaction_count=ticket.dissatisfaction_count,
        escalated_at=ticket.escalated_at,
        category=ticket.category.name if ticket.category else None,
        priority=ticket.priority.name if ticket.priority else None,
        suggested_category=ticket.suggested_category,
        suggested_priority=ticket.suggested_priority,
        category_confidence=ticket.category_confidence,
        priority_confidence=ticket.priority_confidence,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        sla=_to_sla_out(ticket),
        rating=schemas.RatingOut.model_validate(ticket.rating) if ticket.rating else None,
    )
    if include_comments:
        visible_comments = ticket.comments
        if current_user is not None and current_user.role == UserRole.customer:
            visible_comments = [c for c in visible_comments if not c.is_internal_note]
        data["comments"] = [_to_comment_out(c) for c in visible_comments]
        data["attachments"] = [_to_attachment_out(a) for a in ticket.attachments if a.comment_id is None]
        return schemas.TicketDetailOut(**data)
    return schemas.TicketOut(**data)


_get_ticket_or_404 = get_ticket_or_404
_assert_can_view = assert_can_view


# ---------- classification (standalone, used for live suggestions before submit) ----------

@router.post("/classify", response_model=schemas.ClassifyResponse)
def classify_ticket_text(payload: schemas.ClassifyRequest, _=Depends(get_current_user)):
    if not ml_service.models_available():
        raise HTTPException(
            status_code=503,
            detail="ML models not trained yet. Run ml/generate_dataset.py and ml/train.py.",
        )
    result = ml_service.predict(payload.subject, payload.description)
    return schemas.ClassifyResponse(**result)


# ---------- CRUD ----------

@router.post("", response_model=schemas.TicketOut)
def create_ticket(
    payload: schemas.TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prediction = None
    if ml_service.models_available():
        prediction = ml_service.predict(payload.subject, payload.description)

    category_name = payload.category or (prediction["category"] if prediction else None)
    priority_name = prediction["priority"] if prediction else None

    category = db.query(Category).filter(Category.name == category_name).first() if category_name else None
    priority = db.query(Priority).filter(Priority.name == priority_name).first() if priority_name else None

    ticket = Ticket(
        subject=payload.subject,
        description=payload.description,
        customer_id=current_user.id,
        category_id=category.id if category else None,
        priority_id=priority.id if priority else None,
        suggested_category=prediction["category"] if prediction else None,
        suggested_priority=prediction["priority"] if prediction else None,
        category_confidence=prediction["category_confidence"] if prediction else None,
        priority_confidence=prediction["priority_confidence"] if prediction else None,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    if prediction and payload.category:
        ml_feedback_service.record_feedback(
            db, ticket, "category", prediction["category"], payload.category, current_user
        )

    if priority:
        sla_service.create_sla_history_for_ticket(db, ticket, priority)
        db.refresh(ticket)

    # AI-first triage: the AI gets the first attempt at resolving the ticket directly with
    # the customer; a human agent is only bandwidth-assigned once the AI escalates (see
    # ai_triage_service). If GenAI isn't configured/reachable, fall back to the old
    # immediate-assignment behavior so the ticket doesn't sit unhandled.
    try:
        new_comments = ai_triage_service.handle_new_ticket(db, ticket)
    except RuntimeError:
        ticket.handling_mode = TicketHandlingMode.human
        assignment_service.auto_assign(db, ticket)
        db.commit()
        db.refresh(ticket)
        new_comments = []

    ticket_out = _to_ticket_out(ticket)
    manager.broadcast({"type": "ticket.created", "data": ticket_out.model_dump(mode="json")}, ticket_id=ticket.id)
    for comment in new_comments:
        comment_out = _to_comment_out(comment)
        manager.broadcast(
            {"type": "comment.created", "data": comment_out.model_dump(mode="json")},
            ticket_id=ticket.id,
            staff_only=comment.is_internal_note,
        )
    return ticket_out


@router.get("", response_model=List[schemas.TicketOut])
def list_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: Optional[TicketStatus] = Query(None, alias="status"),
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to_me: bool = False,
):
    query = db.query(Ticket)

    if current_user.role == UserRole.customer:
        query = query.filter(Ticket.customer_id == current_user.id)
    elif current_user.role == UserRole.agent:
        # Includes tickets reassigned away from this agent, not just current ones —
        # they keep read-only access (see ticket_access.assert_can_write), so their
        # list shouldn't make those tickets vanish.
        query = query.filter(agent_access_filter(current_user.id))
    elif assigned_to_me:  # admin only, by elimination
        query = query.filter(Ticket.assigned_agent_id == current_user.id)

    if status_filter:
        query = query.filter(Ticket.status == status_filter)
    if priority:
        query = query.join(Priority).filter(Priority.name == priority)
    if category:
        query = query.join(Category).filter(Category.name == category)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    return [_to_ticket_out(t) for t in tickets]


@router.get("/{ticket_id}", response_model=schemas.TicketDetailOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    return _to_ticket_out(ticket, include_comments=True, current_user=current_user)


@router.patch("/{ticket_id}", response_model=schemas.TicketOut)
def update_ticket(
    ticket_id: int,
    payload: schemas.TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    assert_can_write(ticket, current_user)

    reassignment_notice = None
    if payload.assigned_agent_id is not None:
        if current_user.role != UserRole.admin:
            raise HTTPException(status_code=403, detail="Only admins can assign tickets")
        agent = db.query(User).filter(User.id == payload.assigned_agent_id).first()
        if not agent or agent.role not in (UserRole.agent, UserRole.admin) or not agent.is_active:
            raise HTTPException(status_code=400, detail="assigned_agent_id must be an active agent or admin")

        # Capture who/what owned the ticket before we overwrite it below, so the notice
        # (and the reader) can see what actually changed. None of these are worth
        # announcing if the agent isn't actually changing (e.g. a resubmitted form).
        if ticket.handling_mode == TicketHandlingMode.ai:
            previous_handler = "the AI Assistant"
        elif ticket.assigned_agent_id and ticket.assigned_agent_id != agent.id:
            previous_handler = ticket.assigned_agent.name
        else:
            previous_handler = None
        actually_changed = ticket.handling_mode == TicketHandlingMode.ai or ticket.assigned_agent_id != agent.id

        ticket.assigned_agent_id = agent.id
        record_agent_access(ticket, agent.id)
        ticket.assignment_source = AssignmentSource.admin
        ticket.assignment_note = f"Manually reassigned to {agent.name} by {current_user.name}."
        # A human is now explicitly in charge — the AI shouldn't keep replying to the
        # customer's next message just because it hadn't escalated yet on its own.
        ticket.handling_mode = TicketHandlingMode.human

        if actually_changed:
            reassignment_notice = ai_triage_service.post_reassignment_notice(db, ticket, previous_handler, agent.name)

    if payload.category is not None:
        category = db.query(Category).filter(Category.name == payload.category).first()
        if not category:
            raise HTTPException(status_code=400, detail="Unknown category")
        ml_feedback_service.record_feedback(
            db, ticket, "category", ticket.suggested_category, payload.category, current_user
        )
        ticket.category_id = category.id

    if payload.priority is not None:
        priority = db.query(Priority).filter(Priority.name == payload.priority).first()
        if not priority:
            raise HTTPException(status_code=400, detail="Unknown priority")
        ml_feedback_service.record_feedback(
            db, ticket, "priority", ticket.suggested_priority, payload.priority, current_user
        )
        ticket.priority_id = priority.id
        if ticket.sla_history is None:
            sla_service.create_sla_history_for_ticket(db, ticket, priority)

    if payload.status is not None:
        ticket.status = payload.status
        if payload.status == TicketStatus.resolved and ticket.resolved_at is None:
            ticket.resolved_at = datetime.utcnow()
            sla_service.record_resolution(db, ticket)

    db.commit()
    db.refresh(ticket)

    if payload.status == TicketStatus.resolved:
        try:
            rag_service.embed_and_store_ticket(db, ticket)
        except RuntimeError:
            pass  # embedding is best-effort; the ticket status update must still succeed

    if reassignment_notice is not None:
        notice_out = _to_comment_out(reassignment_notice)
        manager.broadcast(
            {"type": "comment.created", "data": notice_out.model_dump(mode="json")},
            ticket_id=ticket.id,
            staff_only=reassignment_notice.is_internal_note,
        )

    ticket_out = _to_ticket_out(ticket)
    manager.broadcast({"type": "ticket.updated", "data": ticket_out.model_dump(mode="json")}, ticket_id=ticket.id)
    return ticket_out


# ---------- comments ----------

@router.post("/{ticket_id}/comments", response_model=schemas.CommentOut)
def add_comment(
    ticket_id: int,
    payload: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    assert_can_write(ticket, current_user)

    if payload.is_internal_note and current_user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Customers cannot post internal notes")

    if ticket.status == TicketStatus.closed and current_user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="This ticket is closed and can no longer receive replies")

    comment = Comment(
        ticket_id=ticket.id,
        author_id=current_user.id,
        body=payload.body,
        is_internal_note=payload.is_internal_note,
    )
    db.add(comment)

    ticket_changed = False
    if current_user.role in (UserRole.agent, UserRole.admin) and not payload.is_internal_note:
        sla_service.record_first_response(db, ticket)
        # A staff member jumping into the thread takes the ticket out of AI-handling,
        # even if the AI hadn't escalated it yet.
        if ticket.handling_mode == TicketHandlingMode.ai:
            ticket.handling_mode = TicketHandlingMode.human
            ticket_changed = True

    db.commit()
    db.refresh(comment)
    comment_out = _to_comment_out(comment)
    manager.broadcast(
        {"type": "comment.created", "data": comment_out.model_dump(mode="json")},
        ticket_id=ticket.id,
        staff_only=comment.is_internal_note,
    )

    extra_comments = []
    if (
        current_user.role == UserRole.customer
        and not payload.is_internal_note
        and ticket.handling_mode == TicketHandlingMode.ai
        and ticket.status not in (TicketStatus.resolved, TicketStatus.closed)
    ):
        try:
            extra_comments = ai_triage_service.handle_customer_message(db, ticket, comment)
            ticket_changed = True
        except RuntimeError:
            pass  # GenAI unavailable — the customer's message just sits until AI/staff can respond

    for extra in extra_comments:
        extra_out = _to_comment_out(extra)
        manager.broadcast(
            {"type": "comment.created", "data": extra_out.model_dump(mode="json")},
            ticket_id=ticket.id,
            staff_only=extra.is_internal_note,
        )

    if ticket_changed:
        ticket_out = _to_ticket_out(ticket)
        manager.broadcast({"type": "ticket.updated", "data": ticket_out.model_dump(mode="json")}, ticket_id=ticket.id)

    return comment_out


# ---------- CSAT ----------

@router.put("/{ticket_id}/rating", response_model=schemas.RatingOut)
def rate_ticket(
    ticket_id: int,
    payload: schemas.RatingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    if current_user.role != UserRole.customer or ticket.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the ticket's customer can rate it")
    if ticket.status not in (TicketStatus.resolved, TicketStatus.closed):
        raise HTTPException(status_code=400, detail="Ticket must be resolved before it can be rated")

    if ticket.rating is None:
        db.add(TicketRating(ticket_id=ticket.id, stars=payload.stars, comment=payload.comment))
    else:
        ticket.rating.stars = payload.stars
        ticket.rating.comment = payload.comment

    db.commit()
    db.refresh(ticket)
    return schemas.RatingOut.model_validate(ticket.rating)


# ---------- AI assignment ----------

@router.post("/{ticket_id}/ai/reassign", response_model=schemas.TicketOut)
def ai_reassign(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admins can trigger AI reassignment")
    ticket = _get_ticket_or_404(db, ticket_id)

    previous_handler = (
        "the AI Assistant" if ticket.handling_mode == TicketHandlingMode.ai
        else ticket.assigned_agent.name if ticket.assigned_agent_id
        else None
    )
    was_ai_handled = ticket.handling_mode == TicketHandlingMode.ai
    previous_agent_id = ticket.assigned_agent_id

    new_agent = assignment_service.auto_assign(db, ticket)
    ticket.handling_mode = TicketHandlingMode.human

    reassignment_notice = None
    if was_ai_handled or ticket.assigned_agent_id != previous_agent_id:
        reassignment_notice = ai_triage_service.post_reassignment_notice(
            db, ticket, previous_handler, new_agent.name if new_agent else "no one (no active agents)"
        )

    db.commit()
    db.refresh(ticket)

    if reassignment_notice is not None:
        notice_out = _to_comment_out(reassignment_notice)
        manager.broadcast(
            {"type": "comment.created", "data": notice_out.model_dump(mode="json")},
            ticket_id=ticket.id,
            staff_only=reassignment_notice.is_internal_note,
        )

    ticket_out = _to_ticket_out(ticket)
    manager.broadcast({"type": "ticket.updated", "data": ticket_out.model_dump(mode="json")}, ticket_id=ticket.id)
    return ticket_out


# ---------- GenAI ----------

@router.post("/{ticket_id}/ai/summarize", response_model=schemas.AITextResponse)
def ai_summarize(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    try:
        text = genai_service.summarize_ticket(ticket)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return schemas.AITextResponse(text=text)


@router.post("/{ticket_id}/ai/draft-reply", response_model=schemas.AITextResponse)
def ai_draft_reply(
    ticket_id: int,
    payload: schemas.AIDraftReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    try:
        text = genai_service.draft_reply(db, ticket, payload.instructions)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return schemas.AITextResponse(text=text)


@router.post("/{ticket_id}/ai/resolution-notes", response_model=schemas.AITextResponse)
def ai_resolution_notes(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_staff)):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    try:
        text = genai_service.generate_resolution_notes(db, ticket)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return schemas.AITextResponse(text=text)


@router.get("/{ticket_id}/similar", response_model=List[schemas.SimilarTicketOut])
def similar_tickets(
    ticket_id: int,
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    ticket = _get_ticket_or_404(db, ticket_id)
    _assert_can_view(ticket, current_user)
    try:
        results = rag_service.find_similar_resolved_tickets(db, ticket, top_k=top_k)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return [
        schemas.SimilarTicketOut(
            id=t.id,
            subject=t.subject,
            status=t.status,
            category=t.category.name if t.category else None,
            priority=t.priority.name if t.priority else None,
            resolved_at=t.resolved_at,
            similarity=round(similarity, 4),
            snippet=(t.description[:220] + "…") if len(t.description) > 220 else t.description,
            viewable=(current_user.role == UserRole.admin or t.assigned_agent_id == current_user.id),
        )
        for t, similarity in results
    ]
