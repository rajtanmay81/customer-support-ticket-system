import json
import secrets
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.models import (
    AssignmentSource,
    Comment,
    Ticket,
    TicketHandlingMode,
    TicketStatus,
    User,
    UserRole,
)
from app.services import assignment_service, genai_service, rag_service
from app.services import sla as sla_service

AI_BOT_EMAIL = "ai-assistant@system.internal"
AI_BOT_NAME = "AI Assistant"

NEGATIVE_SENTIMENTS = ("angry", "frustrated")

_TRIAGE_SYSTEM_PROMPT = (
    "You are an AI customer-support assistant chatting directly with a customer, trying to "
    "resolve their issue yourself before any human agent gets involved. You may be given "
    "reference material from similar past resolved tickets — use it only if genuinely "
    "relevant, and never invent facts, dates, or commitments that aren't supported by the "
    "conversation.\n\n"
    "Read the conversation so far, focusing on the customer's latest message, and respond "
    "with strict JSON only (no markdown, no code fences) matching exactly this shape:\n"
    '{"sentiment": "angry" | "frustrated" | "neutral" | "satisfied", '
    '"wants_human": boolean, "resolved": boolean, "reply": string}\n\n'
    "- sentiment: the emotional tone of the customer's LATEST message.\n"
    "- wants_human: true only if the customer explicitly asks to speak with a human/agent, "
    "or explicitly says they are not satisfied/happy with your response.\n"
    "- resolved: true only if you believe the customer's issue is now fully solved and they "
    "are satisfied — never set this speculatively.\n"
    "- reply: the empathetic, helpful message to send back to the customer. If wants_human "
    "is true, make this a short message acknowledging you're connecting them with a human "
    "agent instead of continuing to troubleshoot. Keep it under 150 words, sign off as "
    "'AI Assistant'."
)


def _get_bot_user(db: Session) -> User:
    bot = db.query(User).filter(User.email == AI_BOT_EMAIL).first()
    if bot is None:
        bot = User(
            name=AI_BOT_NAME,
            email=AI_BOT_EMAIL,
            hashed_password=hash_password(secrets.token_hex(32)),
            role=UserRole.admin,
            # Inactive: this account only exists to author AI comments, never to log
            # in — keeping it inactive hides it from the agent-assignment picker
            # (GET /agents filters on is_active) without needing a dedicated role.
            is_active=False,
        )
        db.add(bot)
        db.flush()
    return bot


def _run_triage(db: Session, ticket: Ticket) -> dict:
    transcript = genai_service.build_thread_transcript(ticket)
    similar = rag_service.find_similar_resolved_tickets_safe(db, ticket, top_k=3)
    user_message = transcript + genai_service.build_similar_context(similar)
    raw = genai_service.call_model(_TRIAGE_SYSTEM_PROMPT, user_message, max_tokens=500, json_mode=True)

    try:
        data = json.loads(raw)
        reply = (data.get("reply") or "").strip()
        if not reply:
            raise ValueError("empty reply")
        return {
            "sentiment": data.get("sentiment") or "neutral",
            "wants_human": bool(data.get("wants_human", False)),
            "resolved": bool(data.get("resolved", False)),
            "reply": reply,
        }
    except (json.JSONDecodeError, ValueError, AttributeError):
        # Model didn't return well-formed JSON — fail safe: show its raw text as the
        # reply rather than losing the response, but never escalate/resolve off of it.
        return {"sentiment": "neutral", "wants_human": False, "resolved": False, "reply": raw.strip()}


def post_reassignment_notice(db: Session, ticket: Ticket, previous_handler: str | None, new_agent_name: str) -> Comment:
    """Post a customer-visible notice announcing a handoff — used both when the AI
    escalates (see _escalate) and when a staff member manually reassigns the ticket
    (see routers/tickets.py update_ticket), so the customer always sees who's handling
    their conversation instead of the assignment silently changing underneath them."""
    if previous_handler:
        body = f"🚩 This conversation has been reassigned from {previous_handler} to {new_agent_name}."
    else:
        body = f"🚩 This conversation has been assigned to {new_agent_name}."
    return _create_ai_comment(db, ticket, body)


def _create_ai_comment(db: Session, ticket: Ticket, body: str, is_internal_note: bool = False) -> Comment:
    bot = _get_bot_user(db)
    comment = Comment(
        ticket_id=ticket.id,
        author_id=bot.id,
        body=body,
        is_internal_note=is_internal_note,
        is_ai_generated=True,
    )
    db.add(comment)
    db.flush()
    return comment


def _mark_resolved(db: Session, ticket: Ticket) -> None:
    ticket.status = TicketStatus.resolved
    ticket.resolved_at = datetime.utcnow()
    sla_service.record_resolution(db, ticket)
    try:
        rag_service.embed_and_store_ticket(db, ticket)
    except RuntimeError:
        pass  # embedding is best-effort; the resolution must still succeed


def _escalate(db: Session, ticket: Ticket, result: dict) -> list[Comment]:
    reason = (
        "the customer asked to speak with a human agent"
        if result["wants_human"]
        else "the customer stayed dissatisfied across multiple replies"
    )
    agent = assignment_service.auto_assign(
        db, ticket, source=AssignmentSource.ai_escalation, note_prefix=f"Escalated by AI ({reason}) — "
    )
    ticket.handling_mode = TicketHandlingMode.human
    ticket.escalated_at = datetime.utcnow()

    agent_name = agent.name if agent else "a support agent"
    handoff_message = (
        f"I've connected you with {agent_name} from our support team — they'll pick this up shortly."
    )
    comments = [_create_ai_comment(db, ticket, handoff_message)]

    try:
        summary = genai_service.summarize_ticket(ticket)
        comments.append(
            _create_ai_comment(db, ticket, f"AI handoff summary:\n{summary}", is_internal_note=True)
        )
    except RuntimeError:
        pass  # handoff summary is a nice-to-have; the escalation itself must still succeed

    return comments


def handle_new_ticket(db: Session, ticket: Ticket) -> list[Comment]:
    """Run right after a ticket is created. The AI always gets a first attempt — this
    never escalates, even if the customer's initial description reads as angry."""
    ticket.handling_mode = TicketHandlingMode.ai
    result = _run_triage(db, ticket)
    comment = _create_ai_comment(db, ticket, result["reply"])
    sla_service.record_first_response(db, ticket)

    if result["resolved"] and not result["wants_human"]:
        _mark_resolved(db, ticket)

    db.commit()
    db.refresh(ticket)
    return [comment]


def handle_customer_message(db: Session, ticket: Ticket, customer_comment: Comment) -> list[Comment]:
    """Run after a customer posts a reply while the ticket is still AI-handled."""
    result = _run_triage(db, ticket)
    customer_comment.sentiment = result["sentiment"]

    dissatisfied = result["wants_human"] or result["sentiment"] in NEGATIVE_SENTIMENTS
    if dissatisfied:
        ticket.dissatisfaction_count += 1

    if ticket.dissatisfaction_count >= settings.ai_escalation_threshold:
        new_comments = _escalate(db, ticket, result)
    else:
        new_comments = [_create_ai_comment(db, ticket, result["reply"])]
        if result["resolved"] and not result["wants_human"]:
            _mark_resolved(db, ticket)

    db.commit()
    db.refresh(ticket)
    return new_comments
