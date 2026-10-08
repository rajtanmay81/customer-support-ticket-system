from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_staff
from app import schemas
from app.models import CannedResponse, Ticket, User, UserRole
from app.services import rag_service
from app.services.ticket_access import assert_can_view, get_ticket_or_404

router = APIRouter(prefix="/canned-responses", tags=["canned-responses"])


def _embed_canned_response(cr: CannedResponse) -> None:
    """Best-effort — a Gemini hiccup should never block saving a canned response, it just
    means the response won't show up ranked in /suggest until the next successful save."""
    embedding = rag_service.embed_text_safe(f"{cr.title}. {cr.body}", task_type="RETRIEVAL_DOCUMENT")
    if embedding is not None:
        cr.embedding = embedding
        cr.embedding_updated_at = datetime.utcnow()


def _to_out(cr: CannedResponse) -> schemas.CannedResponseOut:
    return schemas.CannedResponseOut(
        id=cr.id,
        title=cr.title,
        body=cr.body,
        category=cr.category,
        created_by_id=cr.created_by_id,
        created_by_name=cr.created_by.name,
        created_at=cr.created_at,
        updated_at=cr.updated_at,
    )


def _assert_can_modify(cr: CannedResponse, user: User):
    if cr.created_by_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only the creator or an admin can modify this canned response")


@router.get("", response_model=List[schemas.CannedResponseOut])
def list_canned_responses(
    category: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_staff),
):
    query = db.query(CannedResponse)
    if category:
        query = query.filter(CannedResponse.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(CannedResponse.title.ilike(like), CannedResponse.body.ilike(like)))
    return [_to_out(c) for c in query.order_by(CannedResponse.title).all()]


@router.get("/suggest", response_model=List[schemas.CannedResponseSuggestionOut])
def suggest_canned_responses(
    ticket_id: int,
    top_k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    """Ranks canned responses by semantic relevance to `ticket_id`, instead of requiring
    the agent to know the right keyword. Best-effort: falls back to a plain alphabetical
    list (similarity 0) if embeddings aren't available (no Gemini key, or nothing's been
    embedded yet), matching the fallback style of GET /tickets/{id}/similar."""
    ticket = get_ticket_or_404(db, ticket_id)
    assert_can_view(ticket, current_user)

    query_vector = rag_service.embed_ticket_query_safe(ticket)
    if query_vector is None:
        fallback = db.query(CannedResponse).order_by(CannedResponse.title).limit(top_k).all()
        return [schemas.CannedResponseSuggestionOut(**_to_out(cr).model_dump(), similarity=0.0) for cr in fallback]

    rows = (
        db.query(CannedResponse, CannedResponse.embedding.cosine_distance(query_vector).label("distance"))
        .filter(CannedResponse.embedding.isnot(None))
        .order_by("distance")
        .limit(top_k)
        .all()
    )
    return [
        schemas.CannedResponseSuggestionOut(**_to_out(cr).model_dump(), similarity=round(1 - distance, 4))
        for cr, distance in rows
    ]


@router.post("", response_model=schemas.CannedResponseOut)
def create_canned_response(
    payload: schemas.CannedResponseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    cr = CannedResponse(
        title=payload.title,
        body=payload.body,
        category=payload.category,
        created_by_id=current_user.id,
    )
    _embed_canned_response(cr)
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return _to_out(cr)


@router.patch("/{response_id}", response_model=schemas.CannedResponseOut)
def update_canned_response(
    response_id: int,
    payload: schemas.CannedResponseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    cr = db.query(CannedResponse).filter(CannedResponse.id == response_id).first()
    if cr is None:
        raise HTTPException(status_code=404, detail="Canned response not found")
    _assert_can_modify(cr, current_user)

    if payload.title is not None:
        cr.title = payload.title
    if payload.body is not None:
        cr.body = payload.body
    if payload.category is not None:
        cr.category = payload.category

    if payload.title is not None or payload.body is not None:
        _embed_canned_response(cr)

    db.commit()
    db.refresh(cr)
    return _to_out(cr)


@router.delete("/{response_id}", status_code=204)
def delete_canned_response(
    response_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    cr = db.query(CannedResponse).filter(CannedResponse.id == response_id).first()
    if cr is None:
        raise HTTPException(status_code=404, detail="Canned response not found")
    _assert_can_modify(cr, current_user)
    db.delete(cr)
    db.commit()
