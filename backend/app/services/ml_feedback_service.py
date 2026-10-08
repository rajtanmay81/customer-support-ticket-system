from sqlalchemy.orm import Session

from app.models import MLFeedback, Ticket, User


def record_feedback(
    db: Session,
    ticket: Ticket,
    field: str,
    suggested_value: str | None,
    corrected_value: str,
    user: User,
) -> None:
    """Log a human correction of the ML classifier's suggestion for `field`
    ("category" or "priority"). No-op if there's nothing to learn from (the
    corrected value matches what was already suggested, or there was no ML
    suggestion to compare against in the first place). Only stages the row
    (`db.add`) — the caller's own commit persists it, so this stays part of
    the same all-or-nothing transaction as the rest of the ticket update."""
    if not suggested_value or suggested_value == corrected_value:
        return
    db.add(
        MLFeedback(
            ticket_id=ticket.id,
            field=field,
            suggested_value=suggested_value,
            corrected_value=corrected_value,
            subject=ticket.subject,
            description=ticket.description,
            corrected_by_id=user.id,
        )
    )


def feedback_stats(db: Session) -> dict:
    rows = db.query(MLFeedback).all()
    by_field: dict[str, dict[str, int]] = {}
    for row in rows:
        counts = by_field.setdefault(row.field, {})
        counts[row.corrected_value] = counts.get(row.corrected_value, 0) + 1
    return {
        "total": len(rows),
        "by_field": [
            {"field": field, "count": sum(counts.values()), "corrected_values": counts}
            for field, counts in by_field.items()
        ],
    }


def export_training_rows(db: Session) -> list[dict]:
    """Every MLFeedback row, reshaped into {text, category, priority} rows suitable for
    appending to the training CSV (see ml/build_dataset_with_feedback.py). Each correction
    only tells us the true value of *one* field — the other is left blank and dropped by
    the caller when building the per-classifier training set, since we don't know it."""
    rows = []
    for row in db.query(MLFeedback).all():
        entry = {
            "subject": row.subject,
            "description": row.description,
            "category": row.corrected_value if row.field == "category" else "",
            "priority": row.corrected_value if row.field == "priority" else "",
        }
        rows.append(entry)
    return rows
