from pathlib import Path

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Ticket
from app.services import rag_service

_client = None

MAX_IMAGE_ATTACHMENTS = 4


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def call_model(
    system: str,
    user_message: str,
    max_tokens: int = 1024,
    json_mode: bool = False,
    image_parts: list | None = None,
) -> str:
    # Text generation only — embeddings/RAG (rag_service.py) always use Gemini,
    # regardless of this switch. See config.py / .env.example for details. Groq's chat
    # completions API used here is text-only, so image_parts is simply dropped on that
    # path rather than failing the request over a nice-to-have.
    if settings.groq_api_key:
        return _call_groq(system, user_message, max_tokens, json_mode)
    return _call_gemini(system, user_message, max_tokens, json_mode, image_parts)


def _call_groq(system: str, user_message: str, max_tokens: int, json_mode: bool) -> str:
    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise RuntimeError("Groq API rate limit/quota hit, please try again shortly.")
        raise RuntimeError(f"Groq API error ({e.response.status_code}): {e.response.text}")
    except httpx.HTTPError as e:
        raise RuntimeError(f"Could not reach the Groq API: {e}")

    return response.json()["choices"][0]["message"]["content"] or ""


def _call_gemini(
    system: str, user_message: str, max_tokens: int, json_mode: bool, image_parts: list | None = None
) -> str:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to backend/.env to enable GenAI features."
        )
    contents = [user_message, *image_parts] if image_parts else user_message
    try:
        response = _get_client().models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if json_mode else None,
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

    return response.text or ""


def _collect_image_parts(ticket: Ticket) -> list:
    """Screenshots/images attached to the ticket (or a non-internal reply) as Gemini
    `Part`s, so summarize/draft/notes can actually see what the customer attached instead
    of an agent having to describe it. Capped at MAX_IMAGE_ATTACHMENTS to keep prompt size
    and cost bounded; best-effort — a file missing from disk is silently skipped rather
    than failing the whole GenAI call."""
    candidates = [a for a in ticket.attachments if a.comment_id is None]
    for comment in ticket.comments:
        if comment.is_internal_note:
            continue
        candidates.extend(comment.attachments)

    parts = []
    upload_dir = Path(settings.upload_dir)
    for attachment in candidates:
        if not attachment.content_type.startswith("image/"):
            continue
        file_path = upload_dir / attachment.stored_name
        try:
            data = file_path.read_bytes()
        except OSError:
            continue
        parts.append(genai_types.Part.from_bytes(data=data, mime_type=attachment.content_type))
        if len(parts) >= MAX_IMAGE_ATTACHMENTS:
            break
    return parts


def build_thread_transcript(ticket: Ticket) -> str:
    lines = [
        f"Ticket subject: {ticket.subject}",
        f"Category: {ticket.category.name if ticket.category else 'uncategorized'}",
        f"Priority: {ticket.priority.name if ticket.priority else 'unset'}",
        f"Status: {ticket.status.value}",
        "",
        f"Original request from customer ({ticket.customer.name}):",
        ticket.description,
        "",
        "Conversation so far:",
    ]
    for comment in ticket.comments:
        if comment.is_internal_note:
            continue
        role = "Customer" if comment.author_id == ticket.customer_id else "Support agent"
        lines.append(f"[{role} - {comment.author.name}]: {comment.body}")
    return "\n".join(lines)


def build_similar_context(similar: list[tuple[Ticket, float]]) -> str:
    if not similar:
        return ""
    parts = [
        "",
        "For reference, here is how similar past tickets were resolved. Use this only if "
        "genuinely relevant to the current ticket, and never invent details that aren't "
        "shown here or in the current conversation above:",
    ]
    for past_ticket, score in similar:
        parts.append(f"\n--- Similar resolved ticket #{past_ticket.id} (similarity {score:.2f}) ---")
        parts.append(build_thread_transcript(past_ticket))
    return "\n".join(parts)


def summarize_ticket(ticket: Ticket) -> str:
    transcript = build_thread_transcript(ticket)
    system = (
        "You are a support-desk assistant. Summarize the ticket conversation for a support "
        "agent picking it up for the first time. Be concise (4-6 sentences), capture the "
        "customer's core issue, what has already been tried or communicated, and the current "
        "open question or blocker. If screenshots are attached, factor in what they show."
    )
    return call_model(system, transcript, max_tokens=1024, image_parts=_collect_image_parts(ticket))


def draft_reply(db: Session, ticket: Ticket, instructions: str | None = None) -> str:
    transcript = build_thread_transcript(ticket)
    similar = rag_service.find_similar_resolved_tickets_safe(db, ticket, top_k=3)
    system = (
        "You are a support-desk assistant helping a human agent draft a reply to a customer. "
        "Write a clear, empathetic, professional reply addressing the customer's latest message "
        "and the overall context of the ticket. Do not invent facts, dates, or commitments that "
        "aren't supported by the conversation. If screenshots are attached, use what they actually "
        "show as supporting context. You may be given reference material from similar past "
        "resolved tickets — use it only if genuinely relevant. Sign off as 'Support Team'. "
        "Output only the reply text, no preamble."
    )
    user_message = transcript + build_similar_context(similar)
    if instructions:
        user_message += f"\n\nAdditional instructions from the agent: {instructions}"
    return call_model(system, user_message, max_tokens=1280, image_parts=_collect_image_parts(ticket))


def generate_resolution_notes(db: Session, ticket: Ticket) -> str:
    transcript = build_thread_transcript(ticket)
    similar = rag_service.find_similar_resolved_tickets_safe(db, ticket, top_k=3)
    system = (
        "You are a support-desk assistant. Write concise internal resolution notes for this "
        "ticket, suitable for a knowledge base or handoff record. Include: root cause (if known), "
        "the fix or resolution applied, and any follow-up needed. Use short bullet points. If "
        "screenshots are attached, factor in what they show. You may be given reference material "
        "from similar past resolved tickets — use it only if genuinely relevant."
    )
    user_message = transcript + build_similar_context(similar)
    return call_model(system, user_message, max_tokens=1024, image_parts=_collect_image_parts(ticket))
