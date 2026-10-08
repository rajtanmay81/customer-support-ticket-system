from datetime import datetime

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EMBEDDING_DIM, Ticket, TicketStatus

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _build_embedding_text(ticket: Ticket) -> str:
    lines = [ticket.subject, ticket.description]
    for comment in ticket.comments:
        if comment.is_internal_note:
            continue
        lines.append(comment.body)
    return "\n\n".join(lines)


def _embed(text: str, task_type: str) -> list[float]:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to backend/.env to enable GenAI features."
        )
    try:
        response = _get_client().models.embed_content(
            model=settings.gemini_embedding_model,
            contents=text,
            config=genai_types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
    except genai_errors.ClientError as e:
        if e.code == 429:
            raise RuntimeError("Gemini API rate limit/quota hit, please try again shortly.")
        raise RuntimeError(f"Gemini API error ({e.code}): {e.message}")
    except genai_errors.ServerError as e:
        raise RuntimeError(f"Gemini API error ({e.code}): {e.message}")
    except genai_errors.APIError as e:
        raise RuntimeError(f"Gemini API error: {e}")
    except Exception as e:
        raise RuntimeError(f"Could not reach the Gemini API: {e}")

    return response.embeddings[0].values


def embed_and_store_ticket(db: Session, ticket: Ticket) -> None:
    """Compute and persist the embedding for a resolved ticket. Call once a ticket's
    status is set to `resolved` (or during backfill for pre-existing resolved tickets)."""
    text = _build_embedding_text(ticket)
    if not text.strip():
        return
    ticket.embedding = _embed(text, task_type="RETRIEVAL_DOCUMENT")
    ticket.embedding_updated_at = datetime.utcnow()
    db.add(ticket)
    db.commit()


def find_similar_resolved_tickets(
    db: Session, ticket: Ticket, top_k: int = 5
) -> list[tuple[Ticket, float]]:
    """Return up to top_k resolved tickets (excluding `ticket` itself) most similar to it,
    as (ticket, cosine_similarity) pairs, highest similarity first. The query ticket's text
    is embedded fresh on every call so results always reflect its current content, without
    needing to keep an open ticket's stored embedding in sync as it changes."""
    query_text = _build_embedding_text(ticket)
    if not query_text.strip():
        return []
    query_vector = _embed(query_text, task_type="RETRIEVAL_QUERY")

    rows = (
        db.query(Ticket, Ticket.embedding.cosine_distance(query_vector).label("distance"))
        .filter(Ticket.status == TicketStatus.resolved)
        .filter(Ticket.id != ticket.id)
        .filter(Ticket.embedding.isnot(None))
        .order_by("distance")
        .limit(top_k)
        .all()
    )
    return [(t, 1 - distance) for t, distance in rows]


def find_similar_resolved_tickets_safe(
    db: Session, ticket: Ticket, top_k: int = 5
) -> list[tuple[Ticket, float]]:
    """Best-effort variant for callers that only want extra reference context (drafting
    a reply, AI triage) and would rather proceed without it than fail outright when the
    embeddings backend (Gemini) is unavailable — e.g. its quota is separately exhausted
    from whatever provider is generating the actual text."""
    try:
        return find_similar_resolved_tickets(db, ticket, top_k=top_k)
    except RuntimeError:
        return []


def embed_text_safe(text: str, task_type: str) -> list[float] | None:
    """Best-effort embed of arbitrary text (not ticket-specific) — used for canned
    responses, which have nothing to do with a `Ticket` row. Returns None instead of
    raising if Gemini is unavailable, so saving/using a canned response never depends
    on GenAI being configured."""
    if not text.strip():
        return None
    try:
        return _embed(text, task_type=task_type)
    except RuntimeError:
        return None


def embed_ticket_query_safe(ticket: Ticket) -> list[float] | None:
    """Best-effort query embedding of a ticket's current text (subject + description +
    non-internal comments) — used to rank canned responses by relevance to the ticket
    being worked (see routers/canned_responses.py's /suggest endpoint)."""
    text = _build_embedding_text(ticket)
    return embed_text_safe(text, task_type="RETRIEVAL_QUERY")
