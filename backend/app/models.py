import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Enum, Float
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.database import Base

EMBEDDING_DIM = 768


class UserRole(str, enum.Enum):
    customer = "customer"
    agent = "agent"
    admin = "admin"


class TicketStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class AgentAvailability(str, enum.Enum):
    online = "online"
    busy = "busy"
    offline = "offline"


class AssignmentSource(str, enum.Enum):
    ai = "ai"
    ai_escalation = "ai_escalation"
    admin = "admin"
    unassigned = "unassigned"


class TicketHandlingMode(str, enum.Enum):
    # AI is chatting with the customer directly, trying to resolve the ticket itself.
    ai = "ai"
    # A human agent owns the conversation (either escalated by the AI, or a staff
    # member replied directly / it was manually assigned).
    human = "human"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.customer)
    is_active = Column(Boolean, nullable=False, default=True)
    # Self-reported availability, used by the AI assignment algorithm to route new
    # tickets. Meaningful for agents/admins; unused (default) on customer rows.
    availability = Column(Enum(AgentAvailability), nullable=False, default=AgentAvailability.online)
    created_at = Column(DateTime, default=datetime.utcnow)

    tickets_raised = relationship(
        "Ticket", back_populates="customer", foreign_keys="Ticket.customer_id"
    )
    tickets_assigned = relationship(
        "Ticket", back_populates="assigned_agent", foreign_keys="Ticket.assigned_agent_id"
    )
    comments = relationship("Comment", back_populates="author")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    # e.g. technical_issue, billing, access_issue, product_bug, urgent_escalation

    tickets = relationship("Ticket", back_populates="category")


class Priority(Base):
    __tablename__ = "priorities"

    id = Column(Integer, primary_key=True)
    name = Column(String(20), unique=True, nullable=False)  # low, medium, high, critical
    level = Column(Integer, nullable=False)  # 1=low ... 4=critical, used for sorting/SLA lookup

    tickets = relationship("Ticket", back_populates="priority")
    sla_policy = relationship("SLAPolicy", back_populates="priority", uselist=False)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), nullable=False, default=TicketStatus.open)

    customer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Who/what last set assigned_agent_id, and why — shown in the UI so admins can
    # tell an AI auto-assignment apart from a manual reassignment at a glance.
    assignment_source = Column(Enum(AssignmentSource), nullable=True)
    assignment_note = Column(Text, nullable=True)
    # Comma-separated user ids of every agent who has ever been assigned_agent_id on
    # this ticket (current one included). Lets a reassigned-away agent keep read-only
    # access to a conversation they used to own, instead of losing it outright — see
    # services/ticket_access.py.
    past_agent_ids = Column(Text, nullable=False, default="")

    # AI-first triage: a new ticket starts in `ai` mode with no assigned agent — the AI
    # chatbot tries to resolve it directly. `dissatisfaction_count` tracks how many times
    # the customer has come across as angry/frustrated or explicitly asked for a human
    # since the AI started replying; once it crosses the configured threshold (see
    # services/ai_triage_service.py) the ticket is escalated and handling_mode flips to
    # `human`. Pre-existing rows default to `human` so old tickets aren't retroactively
    # treated as AI-handled.
    handling_mode = Column(Enum(TicketHandlingMode), nullable=False, default=TicketHandlingMode.human)
    dissatisfaction_count = Column(Integer, nullable=False, default=0)
    escalated_at = Column(DateTime, nullable=True)

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    priority_id = Column(Integer, ForeignKey("priorities.id"), nullable=True)

    # ML suggestions, kept separate from the (possibly agent-overridden) final fields above
    suggested_category = Column(String(50), nullable=True)
    suggested_priority = Column(String(20), nullable=True)
    category_confidence = Column(Float, nullable=True)
    priority_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    # RAG: populated once a ticket is resolved (see services/rag_service.py); open/in-progress
    # tickets are queried fresh rather than kept in sync here.
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)

    customer = relationship("User", back_populates="tickets_raised", foreign_keys=[customer_id])
    assigned_agent = relationship("User", back_populates="tickets_assigned", foreign_keys=[assigned_agent_id])
    category = relationship("Category", back_populates="tickets")
    priority = relationship("Priority", back_populates="tickets")
    comments = relationship("Comment", back_populates="ticket", order_by="Comment.created_at")
    sla_history = relationship("SLAHistory", back_populates="ticket", uselist=False)
    rating = relationship("TicketRating", back_populates="ticket", uselist=False)
    attachments = relationship("Attachment", back_populates="ticket", order_by="Attachment.created_at")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    is_internal_note = Column(Boolean, default=False)  # agent-only notes, not shown to customer
    is_ai_generated = Column(Boolean, default=False)
    # Sentiment the AI detected in this message, set only for customer messages analyzed
    # during the AI-triage phase (see services/ai_triage_service.py). One of: angry,
    # frustrated, neutral, satisfied. Null for staff/AI-authored comments and for
    # customer messages sent after the ticket was escalated to a human.
    sentiment = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="comments")
    author = relationship("User", back_populates="comments")
    attachments = relationship("Attachment", back_populates="comment", order_by="Attachment.created_at")


class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id = Column(Integer, primary_key=True)
    priority_id = Column(Integer, ForeignKey("priorities.id"), unique=True, nullable=False)
    response_time_hours = Column(Float, nullable=False)
    resolution_time_hours = Column(Float, nullable=False)

    priority = relationship("Priority", back_populates="sla_policy")


class SLAHistory(Base):
    __tablename__ = "sla_history"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), unique=True, nullable=False)
    sla_policy_id = Column(Integer, ForeignKey("sla_policies.id"), nullable=False)

    response_due_at = Column(DateTime, nullable=False)
    resolution_due_at = Column(DateTime, nullable=False)

    first_response_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    response_breached = Column(Boolean, default=False)
    resolution_breached = Column(Boolean, default=False)

    # Set once a breach has been pushed via WebSocket (services/sla.py:find_newly_breached),
    # so the background sweep in main.py doesn't re-announce the same breach every tick.
    response_breach_notified = Column(Boolean, nullable=False, default=False)
    resolution_breach_notified = Column(Boolean, nullable=False, default=False)

    ticket = relationship("Ticket", back_populates="sla_history")
    sla_policy = relationship("SLAPolicy")


class TicketRating(Base):
    __tablename__ = "ticket_ratings"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), unique=True, nullable=False)
    stars = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="rating")


class CannedResponse(Base):
    __tablename__ = "canned_responses"

    id = Column(Integer, primary_key=True)
    title = Column(String(150), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Best-effort semantic embedding of "title. body" (see services/rag_service.py),
    # used to rank canned responses by relevance to the ticket being worked, instead of
    # requiring the agent to guess the right keyword. Null until first embedded, and left
    # stale (not an error) if Gemini is unavailable when saved.
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_updated_at = Column(DateTime, nullable=True)

    created_by = relationship("User")


class MLFeedback(Base):
    """A record of an agent/customer correcting the ML classifier's suggestion.

    Captured whenever the *official* category/priority ends up different from what
    `ml_service.predict()` suggested (see routers/tickets.py's create_ticket/update_ticket).
    Subject/description are denormalized (copied, not joined) so this row's training value
    survives the ticket being edited or deleted later — see services/ml_feedback_service.py,
    which is also how these rows get folded back into a retrain (the active-learning loop).
    """

    __tablename__ = "ml_feedback"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    field = Column(String(20), nullable=False)  # "category" | "priority"
    suggested_value = Column(String(50), nullable=True)
    corrected_value = Column(String(50), nullable=False)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    corrected_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket")
    corrected_by = relationship("User")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    # null = attached to the ticket itself (raised alongside the original description);
    # set = attached to a specific reply in the thread
    comment_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    stored_name = Column(String(255), unique=True, nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="attachments")
    comment = relationship("Comment", back_populates="attachments")
    uploaded_by = relationship("User")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)

    user = relationship("User")
