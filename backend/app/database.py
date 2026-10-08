from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_pgvector_extension() -> None:
    """Create the pgvector extension if missing. Must run before Base.metadata.create_all(),
    since Ticket.embedding's column type depends on the `vector` type it defines."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()


def ensure_schema_migrations() -> None:
    """Additive, idempotent column backfills for an already-running database.

    This project has no migration framework (see README) — Base.metadata.create_all()
    only creates missing tables, it never alters existing ones. New nullable/defaulted
    columns are therefore added here with ADD COLUMN IF NOT EXISTS so both a fresh DB
    and an existing one (e.g. the docker-compose Postgres volume) pick them up."""
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS availability VARCHAR(20) NOT NULL DEFAULT 'online'",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assignment_source VARCHAR(20)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assignment_note TEXT",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS handling_mode VARCHAR(10) NOT NULL DEFAULT 'human'",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dissatisfaction_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP",
        "ALTER TABLE comments ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20)",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS past_agent_ids TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE canned_responses ADD COLUMN IF NOT EXISTS embedding vector(768)",
        "ALTER TABLE canned_responses ADD COLUMN IF NOT EXISTS embedding_updated_at TIMESTAMP",
        "ALTER TABLE sla_history ADD COLUMN IF NOT EXISTS response_breach_notified BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE sla_history ADD COLUMN IF NOT EXISTS resolution_breach_notified BOOLEAN NOT NULL DEFAULT false",
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
        conn.commit()
