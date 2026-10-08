"""
One-time backfill: compute embeddings for resolved tickets that existed before the
RAG feature was added (or whose embedding failed to save at resolution time).

Run with: python -m app.backfill_embeddings
"""
from app.database import SessionLocal
from app.models import Ticket, TicketStatus
from app.services import rag_service


def backfill():
    db = SessionLocal()
    try:
        tickets = (
            db.query(Ticket)
            .filter(Ticket.status == TicketStatus.resolved, Ticket.embedding.is_(None))
            .all()
        )
        print(f"Found {len(tickets)} resolved ticket(s) without embeddings.")
        for i, ticket in enumerate(tickets, 1):
            try:
                rag_service.embed_and_store_ticket(db, ticket)
                print(f"  [{i}/{len(tickets)}] embedded ticket #{ticket.id}")
            except RuntimeError as e:
                print(f"  [{i}/{len(tickets)}] SKIPPED ticket #{ticket.id}: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
