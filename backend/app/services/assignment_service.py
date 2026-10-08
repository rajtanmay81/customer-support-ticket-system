from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import AgentAvailability, AssignmentSource, Ticket, TicketStatus, User, UserRole
from app.services.ticket_access import record_agent_access

ACTIVE_STATUSES = (TicketStatus.open, TicketStatus.in_progress)


def compute_agent_load(db: Session, agent_id: int) -> int:
    return (
        db.query(Ticket)
        .filter(Ticket.assigned_agent_id == agent_id, Ticket.status.in_(ACTIVE_STATUSES))
        .count()
    )


def _active_agents(db: Session) -> List[User]:
    return db.query(User).filter(User.role == UserRole.agent, User.is_active.is_(True)).all()


def pick_best_agent(db: Session) -> Optional[User]:
    candidates = _active_agents(db)
    if not candidates:
        return None

    online = [a for a in candidates if a.availability == AgentAvailability.online]
    busy = [a for a in candidates if a.availability == AgentAvailability.busy]
    # Prefer agents who are online, then busy, then fall back to everyone active —
    # a ticket should never go unassigned just because nobody toggled themselves online.
    pool = online or busy or candidates

    return min(pool, key=lambda a: compute_agent_load(db, a.id))


def auto_assign(
    db: Session,
    ticket: Ticket,
    source: AssignmentSource = AssignmentSource.ai,
    note_prefix: str = "",
) -> Optional[User]:
    """Returns the agent just assigned (or None if unassigned). Callers that need to
    report the new agent's name should use this return value rather than reading
    ticket.assigned_agent afterward — this function sets the raw assigned_agent_id
    column, which does not refresh an already-loaded assigned_agent relationship on
    the same ticket instance within the same session."""
    agent = pick_best_agent(db)
    if agent is None:
        ticket.assigned_agent_id = None
        ticket.assignment_source = AssignmentSource.unassigned
        ticket.assignment_note = note_prefix + "No active agents exist yet — could not auto-assign."
        return None

    load = compute_agent_load(db, agent.id)
    ticket.assigned_agent_id = agent.id
    record_agent_access(ticket, agent.id)
    ticket.assignment_source = source
    ticket.assignment_note = (
        note_prefix
        + f"Auto-assigned to {agent.name} ({agent.availability.value}) — "
        f"{load} active ticket{'s' if load != 1 else ''} at time of assignment."
    )
    return agent
