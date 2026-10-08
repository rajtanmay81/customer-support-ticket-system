from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Ticket, SLAPolicy, SLAHistory, Priority, TicketStatus


def create_sla_history_for_ticket(db: Session, ticket: Ticket, priority: Priority) -> SLAHistory:
    """Create the SLA clock for a ticket the moment its priority is known."""
    policy = db.query(SLAPolicy).filter(SLAPolicy.priority_id == priority.id).first()
    if policy is None:
        return None

    now = datetime.utcnow()
    sla = SLAHistory(
        ticket_id=ticket.id,
        sla_policy_id=policy.id,
        response_due_at=now + timedelta(hours=policy.response_time_hours),
        resolution_due_at=now + timedelta(hours=policy.resolution_time_hours),
    )
    db.add(sla)
    db.commit()
    db.refresh(sla)
    return sla


def record_first_response(db: Session, ticket: Ticket) -> None:
    sla = ticket.sla_history
    if sla is None or sla.first_response_at is not None:
        return
    now = datetime.utcnow()
    sla.first_response_at = now
    sla.response_breached = now > sla.response_due_at
    db.commit()


def record_resolution(db: Session, ticket: Ticket) -> None:
    sla = ticket.sla_history
    if sla is None or sla.resolved_at is not None:
        return
    now = datetime.utcnow()
    sla.resolved_at = now
    sla.resolution_breached = now > sla.resolution_due_at
    db.commit()


def refresh_breach_flags(sla: SLAHistory) -> SLAHistory:
    """Recompute breach flags for in-flight SLAs (not yet responded/resolved) at read time."""
    now = datetime.utcnow()
    if sla.first_response_at is None and now > sla.response_due_at:
        sla.response_breached = True
    if sla.resolved_at is None and now > sla.resolution_due_at:
        sla.resolution_breached = True
    return sla


def find_newly_breached(db: Session) -> list[tuple[Ticket, str]]:
    """Scan open/in-progress tickets for SLA clocks that have just crossed their due time
    and haven't been announced yet, marking them notified as it goes so a repeat sweep
    (see the background task in main.py) doesn't re-announce the same breach. Returns
    (ticket, "response" | "resolution") pairs, one per newly-crossed clock."""
    now = datetime.utcnow()
    newly_breached: list[tuple[Ticket, str]] = []

    candidates = (
        db.query(Ticket)
        .join(SLAHistory)
        .filter(Ticket.status.in_([TicketStatus.open, TicketStatus.in_progress]))
        .filter(
            (
                (SLAHistory.first_response_at.is_(None))
                & (SLAHistory.response_due_at < now)
                & (SLAHistory.response_breach_notified.is_(False))
            )
            | (
                (SLAHistory.resolved_at.is_(None))
                & (SLAHistory.resolution_due_at < now)
                & (SLAHistory.resolution_breach_notified.is_(False))
            )
        )
        .all()
    )

    for ticket in candidates:
        sla = ticket.sla_history
        if sla.first_response_at is None and sla.response_due_at < now and not sla.response_breach_notified:
            sla.response_breached = True
            sla.response_breach_notified = True
            newly_breached.append((ticket, "response"))
        if sla.resolved_at is None and sla.resolution_due_at < now and not sla.resolution_breach_notified:
            sla.resolution_breached = True
            sla.resolution_breach_notified = True
            newly_breached.append((ticket, "resolution"))

    if newly_breached:
        db.commit()
    return newly_breached
