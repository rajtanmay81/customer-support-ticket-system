from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app import schemas
from app.models import Ticket, Comment, Category, SLAHistory, TicketRating
from app.services.sla import refresh_breach_flags

router = APIRouter(prefix="/admin/analytics", tags=["admin"])

VOLUME_WINDOW_DAYS = 30


@router.get("/overview", response_model=schemas.AnalyticsOverviewOut)
def analytics_overview(db: Session = Depends(get_db), _=Depends(require_admin)):
    since = datetime.utcnow() - timedelta(days=VOLUME_WINDOW_DAYS)

    volume_rows = (
        db.query(func.date(Ticket.created_at).label("day"), func.count(Ticket.id))
        .filter(Ticket.created_at >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    ticket_volume = [{"date": str(day), "count": count} for day, count in volume_rows]

    category_rows = (
        db.query(Category.name, func.count(Ticket.id))
        .join(Ticket, Ticket.category_id == Category.id)
        .group_by(Category.name)
        .all()
    )
    category_distribution = [{"category": name, "count": count} for name, count in category_rows]

    sentiment_rows = (
        db.query(Comment.sentiment, func.count(Comment.id))
        .filter(Comment.sentiment.isnot(None))
        .group_by(Comment.sentiment)
        .all()
    )
    sentiment_counts = [{"sentiment": sentiment, "count": count} for sentiment, count in sentiment_rows]

    # SLA compliance is recomputed live (refresh_breach_flags), same as every other read
    # of an SLAHistory row in the app — a still-open ticket only counts once its clock has
    # actually run out, not merely because no one has responded/resolved it yet.
    response_met = response_breached = resolution_met = resolution_breached = 0
    for sla in db.query(SLAHistory).all():
        refresh_breach_flags(sla)
        if sla.first_response_at is not None and not sla.response_breached:
            response_met += 1
        elif sla.response_breached:
            response_breached += 1
        if sla.resolved_at is not None and not sla.resolution_breached:
            resolution_met += 1
        elif sla.resolution_breached:
            resolution_breached += 1

    avg_rating, rating_count = db.query(func.avg(TicketRating.stars), func.count(TicketRating.id)).first()

    return schemas.AnalyticsOverviewOut(
        ticket_volume=ticket_volume,
        category_distribution=category_distribution,
        sentiment_counts=sentiment_counts,
        sla_response_met=response_met,
        sla_response_breached=response_breached,
        sla_resolution_met=resolution_met,
        sla_resolution_breached=resolution_breached,
        average_rating=round(avg_rating, 2) if avg_rating is not None else None,
        rating_count=rating_count or 0,
    )
