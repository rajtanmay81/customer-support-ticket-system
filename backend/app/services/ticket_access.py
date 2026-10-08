from fastapi import HTTPException
from sqlalchemy import literal, or_
from sqlalchemy.orm import Session

from app.models import Ticket, User, UserRole


def get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def has_had_access(ticket: Ticket, agent_id: int) -> bool:
    """True if `agent_id` is currently assigned to this ticket, or ever was."""
    if ticket.assigned_agent_id == agent_id:
        return True
    if not ticket.past_agent_ids:
        return False
    return str(agent_id) in ticket.past_agent_ids.split(",")


def record_agent_access(ticket: Ticket, agent_id: int) -> None:
    """Call whenever ticket.assigned_agent_id is set, so a later reassignment-away
    can still grant this agent read-only access instead of a hard 403 — see
    assert_can_view/assert_can_write below."""
    ids = set(filter(None, (ticket.past_agent_ids or "").split(",")))
    ids.add(str(agent_id))
    ticket.past_agent_ids = ",".join(sorted(ids, key=int))


def agent_access_filter(agent_id: int):
    """SQLAlchemy filter matching tickets this agent currently has, or ever had,
    access to — mirrors has_had_access() above but as a query filter, used by
    GET /tickets so a reassigned-away agent still sees the ticket in their list
    (read-only) instead of it disappearing."""
    padded = literal(",") + Ticket.past_agent_ids + literal(",")
    return or_(Ticket.assigned_agent_id == agent_id, padded.like(f"%,{agent_id},%"))


def assert_can_view(ticket: Ticket, user: User) -> None:
    """Read gate. A customer sees only their own tickets. An agent sees any ticket
    they are currently OR were ever assigned to (read-only once reassigned away —
    see assert_can_write for the write-side restriction)."""
    if user.role == UserRole.customer and ticket.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket")
    if user.role == UserRole.agent and not has_had_access(ticket, user.id):
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket")


def assert_can_write(ticket: Ticket, user: User) -> None:
    """Write gate, stricter than assert_can_view: a customer may only write on their
    own ticket, and an agent only while they are the CURRENTLY assigned agent — once
    an admin reassigns a ticket away from them, they keep read access (assert_can_view)
    but lose the ability to reply or change anything on it. Admins always pass."""
    if user.role == UserRole.admin:
        return
    if user.role == UserRole.customer and ticket.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this ticket")
    if user.role == UserRole.agent and ticket.assigned_agent_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="This ticket has been reassigned to another agent — you now have read-only access.",
        )
