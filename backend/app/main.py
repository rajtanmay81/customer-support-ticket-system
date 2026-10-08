import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, SessionLocal, engine, ensure_pgvector_extension, ensure_schema_migrations
from app.routers import (
    auth, tickets, reference, users, canned_responses, attachments, ws, ml_admin, analytics,
)
from app.services import sla as sla_service
from app.ws_manager import manager

SLA_BREACH_SWEEP_INTERVAL_SECONDS = 60

ensure_pgvector_extension()
Base.metadata.create_all(bind=engine)
ensure_schema_migrations()

app = FastAPI(
    title="Customer Support Ticket Management System",
    description="POC: ticketing + SLA tracking + ML priority/category prediction + GenAI drafting",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(reference.router)
app.include_router(users.router)
app.include_router(canned_responses.router)
app.include_router(attachments.router)
app.include_router(ws.router)
app.include_router(ml_admin.router)
app.include_router(analytics.router)


async def _sla_breach_sweep_loop():
    """Background task, no external scheduler: every SLA_BREACH_SWEEP_INTERVAL_SECONDS,
    scan for tickets whose SLA clock just crossed its due time and push an `sla.breached`
    WebSocket event — proactive, instead of a breach only surfacing when someone happens
    to open the ticket/list. Runs in-process on the event loop this app already owns,
    matching the no-task-queue architecture used everywhere else (ws_manager.py)."""
    while True:
        await asyncio.sleep(SLA_BREACH_SWEEP_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            for ticket, breach_type in sla_service.find_newly_breached(db):
                manager.broadcast(
                    {
                        "type": "sla.breached",
                        "data": {
                            "ticket_id": ticket.id,
                            "subject": ticket.subject,
                            "breach_type": breach_type,
                            "assigned_agent_id": ticket.assigned_agent_id,
                        },
                    },
                    ticket_id=ticket.id,
                )
        finally:
            db.close()


@app.on_event("startup")
async def _capture_event_loop():
    # Lets sync request handlers (plain `def`, run in FastAPI's threadpool) push
    # WebSocket broadcasts via asyncio.run_coroutine_threadsafe against this loop.
    manager.set_loop(asyncio.get_running_loop())
    asyncio.create_task(_sla_breach_sweep_loop())


@app.get("/health")
def health():
    return {"status": "ok"}
