from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, ConfigDict, field_validator, Field

from app.models import UserRole, TicketStatus, AgentAvailability, AssignmentSource, TicketHandlingMode


# ---------- Auth / Users ----------

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    # role intentionally absent: public registration always creates a customer


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: UserRole
    is_active: bool
    availability: AgentAvailability


class AvailabilityUpdate(BaseModel):
    availability: AgentAvailability


class AgentOut(UserOut):
    active_ticket_count: int


class AdminUserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole

    @field_validator("role")
    @classmethod
    def role_must_be_staff(cls, v):
        if v == UserRole.customer:
            raise ValueError("Admin-created accounts must be agent or admin — customers self-register")
        return v


class AdminUserUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def role_must_be_staff(cls, v):
        if v is not None and v == UserRole.customer:
            raise ValueError("Cannot set role to customer via admin user management")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DemoAccountOut(BaseModel):
    name: str
    role: str
    email: str
    password: str
    avatar_class: str
    initials: str


# ---------- Reference data ----------

class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class PriorityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    level: int


# ---------- Attachments ----------

class AttachmentOut(BaseModel):
    id: int
    ticket_id: int
    comment_id: Optional[int]
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_id: int
    uploaded_by_name: str
    created_at: datetime


# ---------- Comments ----------

class CommentCreate(BaseModel):
    body: str
    is_internal_note: bool = False


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    author_id: int
    author_name: str
    body: str
    is_internal_note: bool
    is_ai_generated: bool
    sentiment: Optional[str] = None
    created_at: datetime
    attachments: List[AttachmentOut] = []


# ---------- SLA ----------

class SLAOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    response_due_at: datetime
    resolution_due_at: datetime
    first_response_at: Optional[datetime]
    resolved_at: Optional[datetime]
    response_breached: bool
    resolution_breached: bool


# ---------- CSAT ----------

class RatingIn(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: Optional[str] = None


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    stars: int
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------- Tickets ----------

class TicketCreate(BaseModel):
    subject: str
    description: str
    # Optional manual override; if omitted, ML predicts it. Priority has no
    # customer override — it's always ML-predicted at creation time (agents
    # can still change it later via TicketUpdate).
    category: Optional[str] = None


class TicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    assigned_agent_id: Optional[int] = None
    category: Optional[str] = None
    priority: Optional[str] = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    description: str
    status: TicketStatus
    customer_id: int
    customer_name: str
    assigned_agent_id: Optional[int]
    assigned_agent_name: Optional[str]
    assignment_source: Optional[AssignmentSource]
    assignment_note: Optional[str]
    handling_mode: TicketHandlingMode
    dissatisfaction_count: int
    escalated_at: Optional[datetime]
    category: Optional[str]
    priority: Optional[str]
    suggested_category: Optional[str]
    suggested_priority: Optional[str]
    category_confidence: Optional[float]
    priority_confidence: Optional[float]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]
    sla: Optional[SLAOut] = None
    rating: Optional[RatingOut] = None


class TicketDetailOut(TicketOut):
    comments: List[CommentOut] = []
    attachments: List[AttachmentOut] = []


# ---------- AI ----------

class ClassifyRequest(BaseModel):
    subject: str
    description: str


class ClassifyResponse(BaseModel):
    category: str
    category_confidence: float
    priority: str
    priority_confidence: float


class AIDraftReplyRequest(BaseModel):
    instructions: Optional[str] = None


class AITextResponse(BaseModel):
    text: str


class SimilarTicketOut(BaseModel):
    id: int
    subject: str
    status: TicketStatus
    category: Optional[str]
    priority: Optional[str]
    resolved_at: Optional[datetime]
    similarity: float
    snippet: str
    viewable: bool


# ---------- Canned responses ----------

class CannedResponseCreate(BaseModel):
    title: str
    body: str
    category: Optional[str] = None


class CannedResponseUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None


class CannedResponseOut(BaseModel):
    id: int
    title: str
    body: str
    category: Optional[str]
    created_by_id: int
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class CannedResponseSuggestionOut(CannedResponseOut):
    similarity: float


# ---------- ML feedback / active learning ----------

class MLFeedbackFieldStats(BaseModel):
    field: str
    count: int
    corrected_values: dict[str, int]


class MLFeedbackStatsOut(BaseModel):
    total: int
    by_field: List[MLFeedbackFieldStats]


class MLClassMetric(BaseModel):
    label: str
    precision: float
    recall: float
    f1_score: float
    support: float


class MLRetrainResultOut(BaseModel):
    dataset_rows: int
    feedback_rows_included: int
    category_metrics: List[MLClassMetric]
    priority_metrics: List[MLClassMetric]


# ---------- Analytics ----------

class DailyCountOut(BaseModel):
    date: str
    count: int


class CategoryCountOut(BaseModel):
    category: str
    count: int


class SentimentCountOut(BaseModel):
    sentiment: str
    count: int


class AnalyticsOverviewOut(BaseModel):
    ticket_volume: List[DailyCountOut]
    category_distribution: List[CategoryCountOut]
    sentiment_counts: List[SentimentCountOut]
    sla_response_met: int
    sla_response_breached: int
    sla_resolution_met: int
    sla_resolution_breached: int
    average_rating: Optional[float]
    rating_count: int


# ---------- Password reset ----------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MessageOut(BaseModel):
    message: str
