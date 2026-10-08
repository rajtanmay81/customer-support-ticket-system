# Customer Support Ticket Management System (POC)

A practice/upskilling project — **not production-ready** (no automated
tests, minimal error handling beyond the happy path, etc.). It demonstrates
a full-stack ticketing system with an AI-first triage chatbot that handles
new tickets directly and escalates to a human on frustration/request, an
ML classifier with an active-learning feedback loop, a GenAI assistant
(Gemini or Groq), retrieval-augmented "similar tickets" and canned-response
suggestions, AI-driven agent assignment, an analytics dashboard, proactive
SLA-breach notifications, file attachments, and live WebSocket updates, all
wired in end to end.

This document is a deep reference: every table, every API route, every
request/response flow, and how the pieces trigger each other. For a quick
setup, jump to [Setup](#setup); for how it all fits together, read
[System architecture](#system-architecture) onward. For a narrative,
presentation-style walkthrough (useful if you need to explain this project
to someone else), see [CODE_EXPLAINED.md](CODE_EXPLAINED.md). For a
non-technical summary suitable for a manager, see
[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).

---

## Table of contents

1. [Stack](#stack)
2. [Project layout](#project-layout)
3. [System architecture](#system-architecture)
4. [Database schema — every table, column, and relationship](#database-schema--every-table-column-and-relationship)
5. [Setup](#setup)
6. [Authentication & authorization flow](#authentication--authorization-flow)
7. [API reference — every endpoint](#api-reference--every-endpoint)
8. [End-to-end flows](#end-to-end-flows)
9. [ML pipeline — how classification actually works](#ml-pipeline--how-classification-actually-works)
10. [ML feedback & active learning](#ml-feedback--active-learning)
11. [GenAI integration — how Gemini/Groq calls actually work](#genai-integration--how-geminigroq-calls-actually-work)
12. [SLA engine — every state transition](#sla-engine--every-state-transition)
13. [Real-time updates — WebSockets](#real-time-updates--websockets)
14. [Agent availability & AI ticket assignment](#agent-availability--ai-ticket-assignment)
15. [AI-first triage — how a new ticket actually starts](#ai-first-triage--how-a-new-ticket-actually-starts)
16. [File attachments](#file-attachments)
17. [Similar tickets — RAG over embeddings](#similar-tickets--rag-over-embeddings)
18. [Canned responses](#canned-responses)
19. [Analytics dashboard](#analytics-dashboard)
20. [Admin features](#admin-features)
21. [Frontend — pages, routing, state](#frontend--pages-routing-state)
22. [Visual design system](#visual-design-system)
23. [Known POC shortcuts (intentional)](#known-poc-shortcuts-intentional)

---

## Stack

- **Backend:** FastAPI + SQLAlchemy + PostgreSQL (with the `pgvector` extension), JWT auth
- **ML:** scikit-learn (TF-IDF + Logistic Regression), trained offline, loaded at runtime — with an active-learning loop that folds human corrections back into a retrain, triggerable from the admin UI
- **GenAI:** Google Gemini API (`google-genai` Python SDK) for text generation *and* embeddings; optionally Groq (`openai/gpt-oss-120b` by default, via its OpenAI-compatible chat-completions endpoint) as a drop-in swap for the text-generation half only — embeddings always stay on Gemini
- **Real-time:** raw WebSockets (FastAPI's built-in support, no Socket.IO/Redis), plus an in-process background sweep that proactively pushes SLA-breach notifications
- **File storage:** local disk (no S3/object storage)
- **Frontend:** React (Vite), axios, React Router
- **Infra:** Docker Compose (Postgres only — backend/frontend run natively)

## Project layout

```
backend/
  app/
    main.py                 FastAPI app instance, CORS config, router registration, WS event-loop wiring,
                             the in-process SLA-breach sweep background task, /health
    config.py                Settings loaded from .env via pydantic-settings (DB, JWT, Gemini, Groq, AI-escalation
                              threshold, uploads, password-reset TTL)
    database.py                SQLAlchemy engine, session factory, get_db(), pgvector extension bootstrap, and
                                ensure_schema_migrations() — additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
                                statements that backfill new columns onto an already-running database (see Setup)
    models.py                    ORM models: User, Category, Priority, Ticket, Comment, SLAPolicy, SLAHistory,
                                  TicketRating, CannedResponse, MLFeedback, Attachment, PasswordResetToken
    schemas.py                      Pydantic request/response models (the API's public contract)
    auth.py                          Password hashing (bcrypt) + JWT encode/decode
    deps.py                          FastAPI dependencies: get_current_user (also rejects deactivated accounts), require_staff, require_admin
    seed.py                          One-time script: reference data + 5 demo staff users (1 admin, 4 agents; customers self-register)
    ws_manager.py                    In-memory WebSocket connection manager (per-ticket rooms + an admin "watch everything" room)
    backfill_embeddings.py           Standalone script: generates embeddings for resolved tickets created before RAG was added
    routers/
      auth.py                        POST /auth/register, /auth/login, GET /auth/me, PATCH /auth/me/availability,
                                      POST /auth/forgot-password, POST /auth/reset-password, GET /auth/demo-accounts
      tickets.py                     Ticket CRUD, comments, SLA wiring, AI actions, ratings, similar-tickets, /tickets/classify
      reference.py                   GET /categories, /priorities, /agents (lookup data)
      users.py                       Admin-only staff account management (/admin/users)
      canned_responses.py            CRUD for reusable reply templates + GET /canned-responses/suggest (semantic ranking)
      attachments.py                 Upload / download / delete files on a ticket or a reply
      ws.py                          WS /ws/tickets/{id} and WS /ws/admin
      ml_admin.py                    Admin-only: GET /admin/ml/feedback-stats, POST /admin/ml/retrain (active-learning loop)
      analytics.py                   Admin-only: GET /admin/analytics/overview (volume, category mix, sentiment, SLA, CSAT)
    services/
      sla.py                          SLA clock creation, first-response/resolution stamping, breach checks,
                                       find_newly_breached() for the proactive breach-notification sweep
      ml_service.py                    Loads .joblib models, predicts category/priority + confidence, reload_models()
                                        for hot-swapping in a freshly retrained model
      ml_feedback_service.py            Logs human corrections of ML suggestions (MLFeedback rows) and reshapes them
                                         into training rows for a retrain — the active-learning loop
      genai_service.py                  Builds ticket transcript (+ screenshot attachments), routes text generation to
                                         Gemini or Groq (call_model), maps errors to HTTP
      rag_service.py                    Builds/queries ticket *and* canned-response embeddings (Gemini embeddings +
                                         pgvector) for "similar tickets" and ranked canned-response suggestions
      ai_triage_service.py              AI-first triage: the AI Assistant bot chats with a new customer directly,
                                         scores sentiment, escalates to a human agent past a dissatisfaction threshold
      assignment_service.py             Picks the best available agent for a new/reassigned/escalated ticket
      password_reset_service.py         Issues + validates single-use, time-limited password-reset tokens
      ticket_access.py                  Single shared "can this user see this ticket?" rule, used by REST and WS routes alike
  ml/
    generate_dataset.py    Synthesizes a labeled historical-ticket CSV from templates
    train.py                 Trains + evaluates both classifiers, saves .joblib artifacts; callable as train_all() too
    build_dataset_with_feedback.py  Appends real MLFeedback corrections on top of the synthetic dataset (active learning)
    artifacts/                  category_model.joblib, priority_model.joblib (generated)
  data/
    historical_tickets.csv             Generated synthetic training data (generated)
    historical_tickets_augmented.csv   Synthetic data + real corrections, written by build_dataset_with_feedback.py (generated)
  uploads/                    Attachment storage (generated; git-ignored) — uuid-named files, originals never stored under their own name
  .env / .env.example        DATABASE_URL, JWT secret, GEMINI_API_KEY/MODEL/EMBEDDING_MODEL, GROQ_API_KEY/MODEL,
                              AI_ESCALATION_THRESHOLD, upload/reset settings
  requirements.txt           Exact pinned versions (from pip freeze)
frontend/
  index.html                 Vite entry HTML: favicon, Google Fonts (Inter), meta description
  src/
    main.jsx                Entry point: mounts <App> wrapped in <AuthProvider> + <BrowserRouter>
    App.jsx                   Route table + auth branching (see Frontend section)
    index.css                  Global stylesheet — design tokens (CSS custom properties), all component styling
    api/client.js               axios instance: baseURL http://localhost:8000, JWT auto-attached
    context/AuthContext.jsx       Holds `user` in React state, JWT in localStorage, availability toggle
    hooks/useWebSocket.js          Generic reconnecting-WebSocket hook used across pages/AppShell
    utils/
      sla.js                        Pure presentation helpers (ring %, remaining time, headline) derived from
                                     the backend's pre-computed breach flags — never re-decides breach state
      files.js                      Attachment `accept` string, file-size formatting, per-content-type icon
      avatar.js                     Deterministic initials + color-class from a name, used by Avatar.jsx
    pages/
      Login.jsx                     Email/password form -> AuthContext.login(); fetches GET /auth/demo-accounts
                                     for one-tap demo logins; links to Forgot password
      Register.jsx                   Signup form (customer accounts only — see Auth section) -> AuthContext.register()
      ForgotPassword.jsx              Request a reset link (always shows a generic "check your email" message)
      ResetPassword.jsx               Consume a reset token (?token=...) and set a new password
      TicketList.jsx                  Ticket table + filters, incl. an "SLA Breaches" quick filter (?sla=breach);
                                       live-updated for admins via WebSocket
      NewTicket.jsx                    Ticket creation form, AI category/priority preview, optional file attachments
      TicketDetail.jsx                  Full ticket view: comments, attachments, SLA panel, ratings, similar tickets,
                                         staff controls, GenAI panel, canned responses (incl. semantic suggestions) —
                                         the largest page by far
      AdminUsers.jsx                   Admin-only: create/deactivate agent & admin accounts
      AdminMonitor.jsx                 Admin-only: live "all active tickets" dashboard over WebSocket
      AdminAnalytics.jsx               Admin-only: charts for ticket volume, category mix, sentiment, SLA compliance, CSAT
      AdminMlFeedback.jsx              Admin-only: ML correction stats + a "Retrain models now" button
    components/
      AppShell.jsx                    Layout shell wrapping every logged-in page: Sidebar + top breadcrumb bar, plus a
                                       site-wide admin WebSocket listener that pops SLA-breach toasts from anywhere
      Sidebar.jsx                      Left rail — role-aware nav links, ticket/breach counts, agent availability toggle, logout
      Badges.jsx                        StatusBadge / PriorityBar / SLABadge (pure display components)
      FilePicker.jsx                    Multi-file picker with type/size hint, used on ticket creation + replies
      AttachmentList.jsx                Renders attachment chips, click-to-download, delete if permitted
      LiveDot.jsx                       Small connected/disconnected indicator fed by useWebSocket's status
      Avatar.jsx                        Colored initials avatar
docker-compose.yml       Postgres 16, image pgvector/pgvector:pg16 (ticket_system_db container, pgvector preinstalled)
CODE_EXPLAINED.md        Presentation-style code walkthrough (companion to this README)
PROJECT_OVERVIEW.md      Non-technical summary for a manager/stakeholder
PRESENTATION_GUIDE.md    Word-for-word script for demoing this project to a manager
PROJECT_PITCH.md         Structured pitch-deck outline (problem, approach, benefits, demo, code flow)
APPLICATION_FLOW.md      A 10-ticket manual QA script mapping sample tickets to the flows they exercise
```

---

## System architecture

```
┌──────────────┐   HTTP/JSON (JWT Bearer) + WebSocket (JWT query param)   ┌───────────────────┐
│   Browser     │ ────────────────────────────────────────────────────▶  │   FastAPI backend   │
│ React (Vite)  │ ◀────────────────────────────────────────────────────  │   :8000             │
│   :5173       │                                                         └─────────┬─────────┘
└──────────────┘                                                                    │
                                                        ┌───────────────┬────────────┼─────────────┬───────────────┐
                                                        ▼               ▼            ▼              ▼               ▼
                                                 ┌────────────┐  ┌──────────┐ ┌──────────────┐ ┌──────────┐  ┌────────────┐
                                                 │ PostgreSQL  │  │ ML models │ │ Gemini (embed-│ │ Local     │  │ In-memory   │
                                                 │ + pgvector  │  │ (.joblib, │ │ dings, always;│ │ disk      │  │ WS manager  │
                                                 │ :5432       │  │ in        │ │ text, unless  │ │ (uploads/) │  │ (connection │
                                                 │ (Docker)    │  │ process)  │ │ Groq is set)  │ │            │  │  rooms)     │
                                                 └────────────┘  └──────────┘ └──────────────┘ └──────────┘  └────────────┘
```

- The **frontend never talks to Postgres, the ML models, Gemini, or the filesystem directly** — everything goes through the FastAPI backend at `localhost:8000`, authenticated with a JWT stored in `localStorage` (sent as an `Authorization` header over HTTP, and as a `?token=` query param on WebSocket connections, since browsers can't set custom headers on the WS handshake).
- The **ML models** are loaded into the FastAPI process's memory on first use (lazy-loaded singleton in `ml_service.py`) — no network call, pure in-process inference.
- **Gemini** is the primary outbound network dependency, used two ways: text generation (`genai_service.py` — AI-first triage replies, summarize / draft reply / resolution notes) and embeddings (`rag_service.py` — similar-ticket search, canned-response ranking). If `GROQ_API_KEY` is set, the text-generation half routes to **Groq** instead — embeddings always stay on Gemini either way.
- **Attachments** are written to a local `uploads/` folder under the backend's working directory, referenced by a randomly generated filename in the DB — there's no cloud storage integration.
- **WebSocket broadcasts** are handled by a single in-memory `ConnectionManager` (`ws_manager.py`) living inside the FastAPI process. Because HTTP route handlers in FastAPI run in a worker thread pool while WebSocket handling runs on the async event loop, the manager captures a reference to that event loop at startup (`main.py`'s `_capture_event_loop`) so a plain synchronous route (e.g. `POST /tickets`) can still push a broadcast via `asyncio.run_coroutine_threadsafe`.

---

## Database schema — every table, column, and relationship

All tables live in the `ticket_system` Postgres database, created via `Base.metadata.create_all()` (no Alembic migrations — the ORM models in `models.py` are the single source of truth for schema). The `pgvector` extension is enabled automatically at startup (`ensure_pgvector_extension()` in `database.py`) since the `tickets.embedding` column depends on it.

**Keeping an existing database in sync:** since `create_all()` only creates *missing* tables and never alters an existing one, every column added to a table after its first release is also applied by hand in `database.py: ensure_schema_migrations()` — a fixed list of idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements, run on every startup right after `create_all()`. This is how a long-running database (e.g. the docker-compose Postgres volume) picks up newer columns like `users.availability`, `tickets.handling_mode`/`dissatisfaction_count`/`escalated_at`/`past_agent_ids`, `comments.sentiment`, `canned_responses.embedding`, and `sla_history.response_breach_notified`/`resolution_breach_notified` without a full migration framework. A fresh database created from scratch gets all of these from `models.py` directly; the statements are no-ops in that case.

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(120) | |
| `email` | String(255) | unique, indexed — used for login |
| `hashed_password` | String(255) | bcrypt hash, never the plaintext |
| `role` | Enum(`customer`, `agent`, `admin`) | default `customer` |
| `is_active` | Boolean | default `True` — a deactivated account can't log in or use an existing token (see [Auth flow](#authentication--authorization-flow)) |
| `availability` | Enum(`online`, `busy`, `offline`) | default `online` — self-reported by agents/admins, feeds AI assignment; meaningless for customers |
| `created_at` | DateTime | set at insert |

Relationships: a user can have many `tickets_raised` (as customer) and many `tickets_assigned` (as agent), and many `comments`.

### `categories`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(50) | unique — one of `technical_issue`, `billing`, `access_issue`, `product_bug`, `urgent_escalation` |

Static reference table, seeded once by `app/seed.py`.

### `priorities`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `name` | String(20) | unique — `low` / `medium` / `high` / `critical` |
| `level` | Integer | 1–4, used for sort order and as the SLA lookup key |

### `sla_policies`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `priority_id` | FK → `priorities.id` | unique — one policy per priority |
| `response_time_hours` | Float | max hours until first agent response |
| `resolution_time_hours` | Float | max hours until resolution |

Seeded defaults:

| Priority | Response | Resolution |
|---|---|---|
| low | 24h | 120h |
| medium | 8h | 48h |
| high | 4h | 24h |
| critical | 1h | 8h |

### `tickets`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `subject` | String(255) | |
| `description` | Text | |
| `status` | Enum(`open`, `in_progress`, `resolved`, `closed`) | default `open` |
| `customer_id` | FK → `users.id` | who raised it, required |
| `assigned_agent_id` | FK → `users.id` | nullable, staff-only field |
| `assignment_source` | Enum(`ai`, `ai_escalation`, `admin`, `unassigned`) | nullable — who/what last set the assignment; lets the UI show "✨ AI assigned" vs "👤 Manual" vs an AI-escalation handoff |
| `assignment_note` | Text | nullable — human-readable explanation, e.g. "Auto-assigned to Mark (online) — 2 active tickets at time of assignment." |
| `past_agent_ids` | Text | comma-separated `users.id`s of every agent ever assigned to this ticket (current one included) — lets a reassigned-away agent keep read-only access instead of losing the ticket outright (see [`ticket_access.py`](backend/app/services/ticket_access.py)) |
| `handling_mode` | Enum(`ai`, `human`) | default `human` — `ai` while the AI assistant is chatting with the customer directly (see [AI-first triage](#ai-first-triage--how-a-new-ticket-actually-starts)); flips to `human` on escalation, on a manual reassignment, or the moment any staff member replies |
| `dissatisfaction_count` | Integer | default `0` — increments each time the AI detects the customer is unhappy or explicitly asks for a human, during the `ai` handling phase; escalates once this hits `AI_ESCALATION_THRESHOLD` |
| `escalated_at` | DateTime | nullable — stamped the moment `handling_mode` flips from `ai` to `human` via escalation (not set on a manual admin reassignment) |
| `category_id` | FK → `categories.id` | nullable — the **official/final** category |
| `priority_id` | FK → `priorities.id` | nullable — the **official/final** priority |
| `suggested_category` | String(50) | nullable — raw ML output, kept even if overridden |
| `suggested_priority` | String(20) | nullable — raw ML output |
| `category_confidence` | Float | nullable — ML softmax probability of the winning class |
| `priority_confidence` | Float | nullable |
| `created_at` | DateTime | |
| `updated_at` | DateTime | auto-updated on any change (`onupdate`) |
| `resolved_at` | DateTime | nullable — stamped once, first time status becomes `resolved` |
| `embedding` | `Vector(768)` (pgvector) | nullable — populated once the ticket is resolved, for similarity search (see [RAG section](#similar-tickets--rag-over-embeddings)); open/in-progress tickets are never given a stored embedding |
| `embedding_updated_at` | DateTime | nullable |

**Why category/priority and suggested_category/suggested_priority are separate columns:** the ML prediction is always recorded for visibility (so you can see "the model said X") even if an agent later overrides the official field. They are deliberately decoupled — updating `category_id` via `PATCH /tickets/{id}` never touches `suggested_category`.

### `comments`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `ticket_id` | FK → `tickets.id` | |
| `author_id` | FK → `users.id` | |
| `body` | Text | |
| `is_internal_note` | Boolean | default False — agent/admin-only; filtered out of the API response for customers (see note below) |
| `is_ai_generated` | Boolean | default False — true for every comment authored by the synthetic AI Assistant `users` row (triage replies, escalation handoff notices, handoff summaries, reassignment notices) |
| `sentiment` | String(20) | nullable — one of `angry`/`frustrated`/`neutral`/`satisfied`; set only on a **customer's** message while it's being analyzed during the AI-triage phase (`handling_mode = ai`); null for staff/AI-authored comments and for customer messages sent after escalation |
| `created_at` | DateTime | ordering key for the thread |

**Note on `is_internal_note` visibility:** enforced on the backend, not just the UI. `POST /comments` rejects customers who try to set the flag (403), and `GET /tickets/{id}` filters the `comments` list server-side based on the requesting user's role — `routers/tickets.py: _to_ticket_out()` drops any comment with `is_internal_note = True` before serializing the response whenever `current_user.role == customer`. Staff (`agent`/`admin`) always see the full thread. Internal notes are also excluded from what Gemini sees (GenAI transcripts) and from what gets embedded (RAG). The same rule applies to WebSocket broadcasts: an internal-note `comment.created` event is broadcast with `staff_only=True`, so customer sockets in that ticket's room never receive it.

### `sla_history`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `ticket_id` | FK → `tickets.id` | unique — one SLA clock per ticket |
| `sla_policy_id` | FK → `sla_policies.id` | which policy was in effect when the clock started |
| `response_due_at` | DateTime | `created_at + response_time_hours` |
| `resolution_due_at` | DateTime | `created_at + resolution_time_hours` |
| `first_response_at` | DateTime | nullable — stamped on first non-internal staff comment |
| `resolved_at` | DateTime | nullable — stamped when status → `resolved` |
| `response_breached` | Boolean | computed, see [SLA engine](#sla-engine--every-state-transition) |
| `resolution_breached` | Boolean | computed |
| `response_breach_notified` | Boolean | default `False` — set once the background sweep (`sla.find_newly_breached()`) has pushed a `sla.breached` WebSocket event for this clock's response deadline, so the sweep never re-announces the same breach on its next tick |
| `resolution_breach_notified` | Boolean | default `False` — same idea, for the resolution deadline |

### `ticket_ratings`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `ticket_id` | FK → `tickets.id` | unique — one rating per ticket |
| `stars` | Integer | 1–5, validated by the API (`Field(ge=1, le=5)`) |
| `comment` | Text | nullable, optional free-text feedback |
| `created_at` / `updated_at` | DateTime | `updated_at` auto-bumps on edit — the same `PUT` endpoint both creates and edits, so a customer can revise their rating after submitting |

Customer satisfaction (CSAT) tracking — only meaningful once a ticket reaches `resolved`/`closed`. See [End-to-end flows](#end-to-end-flows).

### `canned_responses`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `title` | String(150) | shown in the "insert" dropdown |
| `body` | Text | the text that gets inserted into a reply |
| `category` | String(50) | nullable, free-text — optional grouping/filtering tag |
| `created_by_id` | FK → `users.id` | any staff member can create one; only the creator or an admin can edit/delete it |
| `created_at` / `updated_at` | DateTime | |
| `embedding` | `Vector(768)` (pgvector) | nullable — a best-effort semantic embedding of `"{title}. {body}"`, computed on create/edit (`canned_responses.py: _embed_canned_response()`); used to rank templates by relevance in `GET /canned-responses/suggest`. Left stale (not an error) if Gemini is unavailable at save time. |
| `embedding_updated_at` | DateTime | nullable |

### `ml_feedback`

Logs every human correction of the ML classifier's suggestion — the training data for the active-learning loop (see [ML feedback & active learning](#ml-feedback--active-learning)). A row is only ever inserted when the *official* value ends up different from what `ml_service.predict()` suggested; if an agent picks the same category the model already predicted, nothing is recorded (`ml_feedback_service.record_feedback()` no-ops in that case).

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `ticket_id` | FK → `tickets.id` | |
| `field` | String(20) | `"category"` or `"priority"` — which field was corrected |
| `suggested_value` | String(50) | nullable — what the ML model had originally suggested |
| `corrected_value` | String(50) | the value a human actually set |
| `subject` / `description` | String(255) / Text | **denormalized** — copied from the ticket at correction time, not joined, so this row's training value survives the ticket being edited or deleted later |
| `corrected_by_id` | FK → `users.id` | who made the correction (the customer, at ticket creation, if they overrode the category; or the staff member who edited it afterward) |
| `created_at` | DateTime | |

### `attachments`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `ticket_id` | FK → `tickets.id` | required |
| `comment_id` | FK → `comments.id` | nullable — **null means attached to the ticket itself** (uploaded alongside the original description or added later); **set means attached to that specific reply** |
| `uploaded_by_id` | FK → `users.id` | |
| `filename` | String(255) | original filename as the user saw it, preserved for display/download |
| `stored_name` | String(255) | unique — the actual on-disk filename, a random `uuid4().hex` + original extension, never the user-supplied name (avoids collisions and path-traversal issues) |
| `content_type` | String(100) | the MIME type the browser reported at upload time |
| `size_bytes` | Integer | |
| `created_at` | DateTime | |

Allowed types and size limit are enforced server-side, not just in the UI — see [File attachments](#file-attachments).

### `password_reset_tokens`

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | FK → `users.id` | |
| `token_hash` | String(64) | unique — SHA-256 hex digest of the raw token; the raw token itself is never stored, only ever returned once at creation time |
| `created_at` | DateTime | |
| `expires_at` | DateTime | `created_at + 30 minutes` (`settings.password_reset_token_ttl_minutes`), a hard TTL, not sliding |
| `used_at` | DateTime | nullable — null means still valid/unused; set the moment it's consumed (single-use) |

### Entity-relationship summary

```
users 1───* tickets (customer_id)          tickets *───1 categories        tickets 1───1 ticket_ratings
users 1───* tickets (assigned_agent_id)    tickets *───1 priorities        tickets 1───* attachments
users 1───* comments                       tickets 1───1 sla_history       comments 1───* attachments
users 1───* canned_responses               sla_history *───1 sla_policies  users 1───* password_reset_tokens
tickets 1───* comments                     priorities 1───1 sla_policies  tickets 1───* ml_feedback
users 1───* ml_feedback (corrected_by_id)
```

---

## Setup

### 1. Start PostgreSQL

```bash
docker compose up -d
```
This starts the `ticket_system_db` container (Postgres 16 with the `pgvector` extension available), user `ticket_admin` / password `ticket_pass` / db `ticket_system`, exposed on `localhost:5432`.

### 2. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set GEMINI_API_KEY to a Google AI Studio key to enable the
# GenAI text features (summarize/draft/notes) AND the "similar tickets"
# feature, which also calls Gemini (for embeddings, GEMINI_EMBEDDING_MODEL,
# default "gemini-embedding-001"). Both are disabled/fail gracefully
# without a key.

# generate the synthetic historical dataset + train the ML models
python ml/generate_dataset.py
python ml/train.py

# create tables + seed reference data and demo users
python -m app.seed

# run the API
uvicorn app.main:app --reload --port 8000
```

API docs (Swagger UI): http://localhost:8000/docs — every endpoint below is also browsable/testable there.

Other settings in `.env` worth knowing about (all have working defaults, see `app/config.py`):

| Setting | Default | Purpose |
|---|---|---|
| `PASSWORD_RESET_TOKEN_TTL_MINUTES` | `30` | How long a forgot-password link stays valid |
| `UPLOAD_DIR` | `uploads` | Where attachment files are written, relative to the backend's working directory |
| `MAX_UPLOAD_SIZE_MB` | `10` | Per-file upload size limit, enforced server-side |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Text generation (summarize/draft/notes/AI triage) when Groq isn't configured |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Ticket + canned-response embeddings — always Gemini, regardless of `GROQ_API_KEY` |
| `GROQ_API_KEY` | *(empty)* | Optional — if set, all text generation (chat replies, summaries, drafts, resolution notes, sentiment scoring) routes through Groq's chat-completions API instead of Gemini. Embeddings are unaffected. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Which Groq model to call when `GROQ_API_KEY` is set |
| `AI_ESCALATION_THRESHOLD` | `2` | How many times a customer can read as angry/frustrated (or explicitly ask for a human) during AI-first triage before the ticket escalates to a human agent — see [AI-first triage](#ai-first-triage--how-a-new-ticket-actually-starts) |

Demo logins created by the seed script (all staff — a fresh database has no demo *customer* account, since customers can only ever be created by self-registering via `POST /auth/register` / the Register page):

| Name | Role | Email | Password |
|---|---|---|---|
| Peter | Admin | peter@gmail.com | admin123 |
| Mark | Agent | mark@gmail.com | agent123 |
| Brock | Agent | brock@gmail.com | brock123 |
| Emma | Agent | emma@gmail.com | emma123 |
| Bella | Agent | bella@gmail.com | bella123 |

You don't need to remember these by hand: the Login page calls `GET /auth/demo-accounts` (public, no auth) and renders a "tap to sign in" list for whichever of these users currently exist and are active — edit or deactivate one of these rows in the DB (or via [Admin features](#admin-features)) and the login page picker reflects that on next load. The plaintext passwords above are hardcoded alongside the lookup (`routers/auth.py: DEMO_LOGINS`) since only the bcrypt hash is recoverable from the database.

**Backfilling embeddings for pre-existing resolved tickets:** if you seed/import resolved tickets that predate the RAG feature (or created while `GEMINI_API_KEY` was unset), they won't show up in "similar tickets" results until embedded. Run `python -m app.backfill_embeddings` (or the script directly) to generate embeddings for any resolved ticket that's missing one.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173. The frontend expects the API at `http://localhost:8000` (hardcoded in `src/api/client.js`, and separately in `src/hooks/useWebSocket.js` for the `ws://` base URL) and is CORS-allowed from `http://localhost:5173` only (see `main.py`).

---

## Authentication & authorization flow

1. **Register or log in.** `POST /auth/register` always creates a `customer` account — there's no way for a member of the public to self-register as staff (the request schema, `UserCreate`, has no `role` field at all). Staff accounts (`agent`/`admin`) can only be created by an existing admin, via [Admin features](#admin-features). Both `/auth/register` and `POST /auth/login` return `{ access_token, token_type: "bearer", user: {...} }`.
2. The frontend stores `access_token` in `localStorage` under the key `token` (`AuthContext.jsx`).
3. Every subsequent axios request has an interceptor (`api/client.js`) that reads that token and sets `Authorization: Bearer <token>` automatically. WebSocket connections instead pass the token as a `?token=` query string parameter, since the browser `WebSocket` API can't set custom headers.
4. On the backend, `deps.get_current_user` decodes the JWT, reads the `sub` claim (the user id), and loads the `User` row fresh from the DB on **every request** — there's no server-side session or token cache. It also rejects the request with `403 "Account has been deactivated"` if `user.is_active` is `False` — so deactivating a staff account (see [Admin features](#admin-features)) immediately invalidates any token they're still holding, not just future logins. `POST /auth/login` independently checks the same flag before issuing a new token.
5. Tokens are signed with HS256 using `JWT_SECRET_KEY` from `.env` and expire after `JWT_EXPIRE_MINUTES` (default 1440 = 24h). There's no refresh-token flow — once expired, the user must log in again.
6. **Role gates**, layered on top of `get_current_user`:
   - `require_staff` — allows `agent` or `admin`, else `403`.
   - `require_admin` — allows only `admin`, else `403`.
   - Plain `get_current_user` — any authenticated (and active) role.
7. **Row-level check** (not a dependency, called manually via the shared `app/services/ticket_access.py`): `assert_can_view` —
   - a `customer` can only view a ticket where `ticket.customer_id == current_user.id`;
   - an **agent can only view a ticket assigned to them** (`ticket.assigned_agent_id == current_user.id`) — agents do *not* have blanket visibility into every ticket, only their own queue;
   - an `admin` can view any ticket, no restriction.
   This same function backs `GET /tickets/{id}`, the WebSocket ticket-room join, and the attachment routes, so the rule is enforced consistently everywhere a single ticket is accessed. The **list** endpoint (`GET /tickets`) applies the equivalent filter at the query level (see [API reference](#api-reference--every-endpoint)).
8. **Password reset** (no auth required, both public): `POST /auth/forgot-password {email}` always returns the same generic message whether or not the email exists (anti-enumeration); if it does exist and the account is active, a single-use token is generated (SHA-256 hash stored, raw token never persisted) and — since there's no real email integration in this POC — the reset link is printed to the **backend server console** instead of being emailed. `POST /auth/reset-password {token, new_password}` validates the token (exists, unused, not expired) and overwrites the password; using a token also invalidates any other outstanding tokens for that user. Frontend: [ForgotPassword.jsx](frontend/src/pages/ForgotPassword.jsx) and [ResetPassword.jsx](frontend/src/pages/ResetPassword.jsx), linked from the Login page.

On page load, `AuthContext` calls `GET /auth/me` with whatever token is in `localStorage` to rehydrate `user` — if that fails (expired/invalid/deactivated), it clears the token and the app redirects to `/login`.

---

## API reference — every endpoint

Base URL: `http://localhost:8000`. All routes except `/auth/register`, `/auth/login`, `/auth/forgot-password`, `/auth/reset-password`, and `/health` require `Authorization: Bearer <token>`.

### Auth (`app/routers/auth.py`)

| Method & path | Auth | Body | Response | Notes |
|---|---|---|---|---|
| `POST /auth/register` | none | `{name, email, password}` | `Token` | Always creates a `customer` account. 400 if email taken. |
| `POST /auth/login` | none | `{email, password}` | `Token` | 401 on bad credentials (same message for "no such user" and "wrong password") or a deactivated account. |
| `GET /auth/me` | any user | — | `UserOut` | Used by the frontend on load to rehydrate the session. |
| `PATCH /auth/me/availability` | staff only | `{availability}` | `UserOut` | Sets your own online/busy/offline status; broadcasts `agent.availability_changed` to the admin WebSocket room. |
| `POST /auth/forgot-password` | none | `{email}` | `MessageOut` | Always returns the same generic message. Prints the reset link to the server console (dev email stand-in). |
| `POST /auth/reset-password` | none | `{token, new_password}` | `MessageOut` | 400 if the token is invalid, already used, or expired. |
| `GET /auth/demo-accounts` | none | — | `DemoAccountOut[]` | Public. Returns the still-active demo users from a hardcoded name/password list (`DEMO_LOGINS`), each with a display name, role, email, plaintext password, and avatar styling — powers the "tap to sign in" list on the Login page. Never derived from real user data beyond name/role/email (passwords can't be read back from the DB). |

### Reference data (`app/routers/reference.py`)

| Method & path | Auth | Response | Notes |
|---|---|---|---|
| `GET /categories` | any user | `CategoryOut[]` | Sorted alphabetically. |
| `GET /priorities` | any user | `PriorityOut[]` | Sorted by `level` (low → critical). |
| `GET /agents` | staff only | `AgentOut[]` | Active users with role `agent` or `admin`, each including `active_ticket_count` (open + in-progress tickets currently assigned to them). Populates the "Assigned agent" dropdown. |

### Admin — user management (`app/routers/users.py`, prefix `/admin/users`)

| Method & path | Auth | Body | Response | Notes |
|---|---|---|---|---|
| `GET /admin/users` | admin only | — | `UserOut[]` | All users, including customers. |
| `POST /admin/users` | admin only | `{name, email, password, role}` | `UserOut` | `role` must be `agent` or `admin` (validated); 400 if `customer` or if email taken. This is the *only* way to create staff accounts. |
| `PATCH /admin/users/{id}` | admin only | `{role?, is_active?}` | `UserOut` | 400 if the target is a customer (can't be edited here), or if `role: customer` is requested, or if an admin tries to demote/deactivate **their own** account. |

### Tickets (`app/routers/tickets.py`)

| Method & path | Auth | Body / Query | Response | Notes |
|---|---|---|---|---|
| `POST /tickets/classify` | any user | `{subject, description}` | `ClassifyResponse` | Live preview only — **does not create a ticket**. Runs the ML models directly. 503 if models aren't trained yet. |
| `POST /tickets` | any user | `TicketCreate {subject, description, category?}` | `TicketOut` | See [ticket creation flow](#flow-1-creating-a-ticket) below. Auto-assigns an agent and starts the SLA clock. |
| `GET /tickets` | any user | query: `status?, priority?, category?, assigned_to_me?` | `TicketOut[]` | Customers: hard-filtered to their own tickets. **Agents: hard-filtered to tickets assigned to them** (their own queue only — `assigned_to_me` is irrelevant for them, they never see unassigned or other agents' tickets here). Admins: see everything by default, or only their own assigned tickets if `assigned_to_me=true`. Sorted newest first. |
| `GET /tickets/{id}` | any user (row-checked) | — | `TicketDetailOut` (includes `comments[]`, `attachments[]`) | 404 if missing, 403 per the visibility rule in [Auth flow](#authentication--authorization-flow). |
| `PATCH /tickets/{id}` | staff only | `TicketUpdate {status?, assigned_agent_id?, category?, priority?}` | `TicketOut` | Partial update. Manual `assigned_agent_id` changes are **admin-only** (403 for a plain agent) and set `assignment_source = admin`. See [ticket update flow](#flow-3-staff-updates-a-ticket). |
| `POST /tickets/{id}/comments` | any user (row-checked) | `CommentCreate {body, is_internal_note?}` | `CommentOut` | 403 if a customer sets `is_internal_note: true`. First non-internal staff comment stamps SLA `first_response_at`. Broadcasts `comment.created` over WebSocket. |
| `PUT /tickets/{id}/rating` | customer only, own ticket | `RatingIn {stars: 1-5, comment?}` | `RatingOut` | 400 unless the ticket is `resolved` or `closed`. Upsert — same endpoint creates and edits. |
| `GET /tickets/{id}/similar` | staff only | query: `top_k?` (1–20, default 5) | `SimilarTicketOut[]` | Semantic similarity against past **resolved** tickets. See [RAG section](#similar-tickets--rag-over-embeddings). |
| `POST /tickets/{id}/ai/reassign` | admin only | — | `TicketOut` | Re-runs the AI auto-assignment algorithm on demand. Broadcasts `ticket.updated`. |
| `POST /tickets/{id}/ai/summarize` | staff only | — | `AITextResponse {text}` | 502 if Gemini call fails (bad/missing key, rate limit, network). |
| `POST /tickets/{id}/ai/draft-reply` | staff only | `{instructions?}` | `AITextResponse` | Optional free-text steering appended to the prompt. |
| `POST /tickets/{id}/ai/resolution-notes` | staff only | — | `AITextResponse` | |

### Attachments (`app/routers/attachments.py`)

| Method & path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|
| `POST /tickets/{ticket_id}/attachments` | any user (row-checked) | multipart: `files[]`, optional `comment_id` | `AttachmentOut[]` | See [File attachments](#file-attachments) for validation rules. 403 if a customer tries to attach to a `closed` ticket. |
| `GET /attachments/{id}/download` | any user (row-checked via the parent ticket) | — | file stream | 404 if the DB row or the on-disk file is missing. |
| `DELETE /attachments/{id}` | any user (row-checked) | — | 204 | Only the uploader or an admin can delete. |

### Canned responses (`app/routers/canned_responses.py`)

| Method & path | Auth | Body / Query | Response | Notes |
|---|---|---|---|---|
| `GET /canned-responses` | staff only | query: `category?, q?` | `CannedResponseOut[]` | `q` does a substring search over title + body. |
| `GET /canned-responses/suggest` | staff only | query: `ticket_id, top_k?` (1–10, default 3) | `CannedResponseSuggestionOut[]` | Ranks templates by semantic similarity to the given ticket (embeds the ticket, cosine-distance against every embedded canned response). Falls back to a plain alphabetical list with `similarity: 0.0` if embeddings aren't available (no Gemini key, or nothing embedded yet). Powers the "Suggested for this ticket" chips on `TicketDetail.jsx`. |
| `POST /canned-responses` | staff only | `{title, body, category?}` | `CannedResponseOut` | `created_by_id` = the caller. Best-effort embeds the new template immediately. |
| `PATCH /canned-responses/{id}` | staff only | any field, all optional | `CannedResponseOut` | 403 unless you're the creator or an admin. Re-embeds if `title` or `body` changed. |
| `DELETE /canned-responses/{id}` | staff only | — | 204 | Same creator-or-admin rule. |

### ML admin — active learning (`app/routers/ml_admin.py`, prefix `/admin/ml`)

| Method & path | Auth | Response | Notes |
|---|---|---|---|
| `GET /admin/ml/feedback-stats` | admin only | `MLFeedbackStatsOut` | Total correction count, broken down by field (`category`/`priority`) with a per-value tally (`{"technical_issue": 12, "billing": 3, ...}`), read straight from the `ml_feedback` table. |
| `POST /admin/ml/retrain` | admin only | `MLRetrainResultOut` | Rebuilds the training CSV (synthetic dataset + every `ml_feedback` correction so far, via `ml/build_dataset_with_feedback.py`), retrains both classifiers in-process (`ml/train.py: train_all()`), then calls `ml_service.reload_models()` so the freshly trained models take effect immediately — **no API restart needed**. Synchronous: runs within the request/response cycle since the dataset and models are small (PoC-scale TF-IDF + logistic regression). Returns the new dataset's row count, how many of those rows came from real corrections, and full per-class precision/recall/F1/support for both classifiers. |

### Analytics (`app/routers/analytics.py`, prefix `/admin/analytics`)

| Method & path | Auth | Response | Notes |
|---|---|---|---|
| `GET /admin/analytics/overview` | admin only | `AnalyticsOverviewOut` | One aggregate payload for the Analytics dashboard: daily ticket counts for the last 30 days, ticket counts per category, comment counts per AI-detected sentiment, SLA response/resolution met-vs-breached counts (recomputed live via `refresh_breach_flags()`, same as every other SLA read in the app — a still-open ticket only counts once its clock has actually run out), and the average CSAT star rating + rating count across all `ticket_ratings`. Nothing here is pre-aggregated/cached — every call re-queries the live tables. |

### WebSockets (`app/routers/ws.py`)

| Path | Auth | Notes |
|---|---|---|
| `WS /ws/tickets/{id}?token=<jwt>` | any user, row-checked (same `assert_can_view` rule as `GET /tickets/{id}`) | Closes with code `4401` (bad token) or `4403` (not authorized / ticket doesn't exist). Receive-only from the server's perspective — the client never sends messages, the connection just stays open to receive pushed events. |
| `WS /ws/admin?token=<jwt>` | admin only | Closes `4403` for non-admins (note: a plain agent cannot open this, unlike `GET /agents`). Receives every ticket/comment/availability event system-wide. |

See [Real-time updates](#real-time-updates--websockets) for the full list of event types.

### Misc

| Method & path | Auth | Response |
|---|---|---|
| `GET /health` | none | `{"status": "ok"}` |
| `GET /docs`, `GET /openapi.json` | none | Auto-generated Swagger UI / OpenAPI schema (FastAPI default) |

---

## End-to-end flows

Each flow below ends with a **Tables touched** line — the exact rows read or
written, in order — so you can trace "an action in the UI" all the way down to
"a column in Postgres" without guessing.

### Flow 1: Creating a ticket

`NewTicket.jsx` → `POST /tickets` → `routers/tickets.py: create_ticket()`

1. Frontend collects `subject`, `description`, an optional manual `category` override, and optional file attachments.
2. Optionally, before submitting, the user clicks **"Suggest category & priority (AI)"** → `POST /tickets/classify` — a live preview that runs the ML model but doesn't save anything (no table writes at all).
3. On submit, the backend:
   - If `ml_service.models_available()`, runs `ml_service.predict(subject, description)` regardless of whether the user supplied a category override — the model's raw guess is **always** computed and stored in `suggested_category` / `suggested_priority` / `*_confidence`. Priority itself has no customer override at creation — it's always ML-predicted (an agent can change it afterward).
   - The **official** `category_id` = the user's explicit choice if given, else the ML prediction; `priority_id` = the ML prediction.
   - Inserts the `tickets` row, commits, refreshes.
   - If the user's category choice differs from the ML prediction, `ml_feedback_service.record_feedback()` logs an `ml_feedback` row — see [ML feedback & active learning](#ml-feedback--active-learning).
   - **If a priority was resolved**, immediately calls `sla_service.create_sla_history_for_ticket()` — this inserts a `sla_history` row and starts the SLA clock.
   - **AI-first triage** (`ai_triage_service.handle_new_ticket()`) then takes over — **not** immediate human assignment:
     - `tickets.handling_mode` is set to `'ai'`.
     - The ticket transcript (+ any similar past tickets, read-only from `tickets.embedding`) is sent to Gemini/Groq; the reply is inserted as a `comments` row authored by a synthetic **AI Assistant** `users` row (created once, lazily, the first time any AI action needs to post — email `ai-assistant@system.internal`, `is_active = false` so it's invisible to the agent picker).
     - That AI reply also stamps `sla_history.first_response_at` (`sla_service.record_first_response()`) — the AI's own reply counts as the first response.
     - If the AI judges the issue solved, `tickets.status` → `resolved`, `tickets.resolved_at` is stamped, `sla_history.resolved_at`/`resolution_breached` are set, and `tickets.embedding`/`embedding_updated_at` are populated via `rag_service.embed_and_store_ticket()` — all in the same request, with no human ever touching the ticket.
   - **Fallback**: if the AI call itself fails (Gemini/Groq unreachable or unconfigured), the system falls back to the old behavior instead — `tickets.handling_mode` → `'human'` and `assignment_service.auto_assign()` runs immediately, writing `tickets.assigned_agent_id` / `assignment_source` / `assignment_note`, plus `tickets.past_agent_ids` (via `record_agent_access()`) so that agent keeps permanent read access even if later reassigned.
   - Broadcasts `ticket.created` (and a `comment.created` for the AI's reply, if any) over WebSocket to that ticket's room and the admin room — WebSocket pushes never touch a table, they're in-memory only.
4. If files were attached, the frontend makes a second call, `POST /tickets/{id}/attachments`, after the ticket exists (best-effort — a failed upload doesn't block navigation) — inserts an `attachments` row per file (`comment_id = null` since it's attached to the ticket itself, not a reply).
5. Returns the full `TicketOut`, and the frontend navigates to `/tickets/{id}`.

**Tables touched:** `tickets` (insert, then update for `handling_mode`/status/embedding) → `sla_history` (insert, then update) → `users` (insert, once ever, for the AI bot) → `comments` (insert, AI's reply) → `attachments` (insert, if files chosen).

### Flow 2: Viewing the ticket list

`TicketList.jsx` → `GET /tickets?status=&priority=&category=&assigned_to_me=` on mount and whenever any filter changes.
- Customers: hard-filtered to `customer_id == current_user.id` server-side.
- Agents: hard-filtered to *currently or ever* `assigned_agent_id`/`past_agent_ids` matching them (`ticket_access.agent_access_filter()`) — an agent's ticket list is their queue plus read-only history, nothing more.
- Admins: no filter by default (see everything); can opt into "assigned to me" via the checkbox.
- Each row's SLA badge (`SLABadge` component) reflects `ticket.sla.response_breached || ticket.sla.resolution_breached`, computed live server-side on every fetch — a read of `sla_history`, not a write.
- For admins, the list also opens a `/ws/admin` WebSocket connection and live-merges `ticket.created`/`ticket.updated` events as they arrive, so new tickets appear without a manual refresh.

**Tables touched:** `tickets` (read, joined to `categories`/`priorities`) → `sla_history` (read only, via the `sla` relationship). No writes on this flow.

### Flow 3: Staff updates a ticket

`TicketDetail.jsx` (staff-only "Manage ticket" panel) → `PATCH /tickets/{id}` with one field at a time (each dropdown's `onChange` fires its own PATCH):
- **Status → `resolved`**: if this is the *first* time the ticket reaches `resolved`, `tickets.resolved_at` is stamped, `sla_service.record_resolution()` runs (updating `sla_history.resolved_at` and `resolution_breached`), and `rag_service.embed_and_store_ticket()` writes `tickets.embedding`/`embedding_updated_at` so the ticket becomes searchable in future "similar tickets" results. **Embedding failure is silently swallowed** (wrapped in `try/except RuntimeError: pass`) — if Gemini is unreachable or misconfigured at that moment, the ticket resolves normally but simply never gets an embedding (until backfilled).
- **Category / Priority change**: looked up by name, updates `tickets.category_id`/`priority_id`; if changing priority and no SLA clock exists yet, a new `sla_history` row is inserted now, timed from *this* moment. If the new value differs from the ticket's ML `suggested_category`/`suggested_priority`, `ml_feedback_service.record_feedback()` logs an `ml_feedback` row either way.
- **Assigned agent (manual)**: **admin-only**; validated to be an active `agent` or `admin` user; updates `tickets.assigned_agent_id`, sets `assignment_source = admin` with a note recording who reassigned it and to whom, appends to `tickets.past_agent_ids`, and forces `tickets.handling_mode = 'human'` (a manual assignment always takes the ticket out of AI-handling). If the assignee actually changed, an `ai_triage_service.post_reassignment_notice()` call also inserts a customer-visible `comments` row ("🚩 reassigned from X to Y"), authored by the same AI-bot `users` row used for triage replies.
- Every successful field update triggers `loadTicket()` on the frontend, and also broadcasts `ticket.updated` (and `comment.created` for the reassignment notice, if any) over WebSocket so anyone else watching this ticket (or an admin watching everything) sees the change live.

**Tables touched:** `tickets` (update) → `sla_history` (update, or insert if none existed) → `tickets.embedding` (update, on resolve) → `comments` (insert, only on a manual reassignment that actually changes the agent).

### Flow 4: Posting a comment / reply

`TicketDetail.jsx` "Add a reply" form → `POST /tickets/{id}/comments` (optionally followed by `POST /tickets/{id}/attachments` with `comment_id` set, for files attached to that specific reply):
- Row-level check via `assert_can_view`/`assert_can_write` (the latter blocks an agent who's been reassigned away — see [Authorization model](#authorization-model-explained-simply)).
- Customers are blocked from setting `is_internal_note: true` (403), and from replying at all on a `closed` ticket.
- Inserts the `comments` row.
- **If the author is staff and the comment is not an internal note**: `sla_service.record_first_response()` runs (updates `sla_history.first_response_at`/`response_breached`, idempotent — only the first qualifying comment counts), and if the ticket was still `handling_mode = 'ai'`, it flips to `'human'` (a staff reply always ends AI-handling, even below the escalation threshold).
- **If the author is the customer and the ticket is still `handling_mode = 'ai'`** (and not resolved/closed): `ai_triage_service.handle_customer_message()` runs —
  - Updates `comments.sentiment` **on the customer's own comment row just inserted** (`angry`/`frustrated`/`neutral`/`satisfied`, from the AI's read of the message).
  - If the sentiment is negative or the customer asked for a human, increments `tickets.dissatisfaction_count`.
  - Below the escalation threshold (`AI_ESCALATION_THRESHOLD`, default 2): inserts another `comments` row with the AI's next reply; if the AI judges the issue solved, also resolves the ticket (same `tickets`/`sla_history`/`tickets.embedding` writes as the resolve path in Flow 3).
  - At/above the threshold: escalates — `assignment_service.auto_assign()` writes `tickets.assigned_agent_id`/`assignment_source = ai_escalation`/`assignment_note`/`past_agent_ids`, plus `tickets.handling_mode = 'human'` and `tickets.escalated_at`; inserts a customer-visible handoff `comments` row and, best-effort, an **internal** AI-generated handoff-summary `comments` row (`is_internal_note = true`).
- Broadcasts `comment.created` for each inserted comment (and `ticket.updated` if `handling_mode`/assignment changed); internal notes are broadcast with `staff_only=True` so customer sockets never receive them, mirroring the REST filtering.

**Tables touched:** `comments` (insert — the reply itself, plus any AI reply/handoff/summary comments) → `sla_history` (update, on first staff response or resolution) → `tickets` (update — `handling_mode`, `dissatisfaction_count`, `assigned_agent_id`, `escalated_at`, `status`/`resolved_at`, `embedding`, as applicable).

### Flow 5: GenAI actions (summarize / draft reply / resolution notes)

`TicketDetail.jsx` "GenAI assistant" panel (staff-only) → `POST /tickets/{id}/ai/{summarize|draft-reply|resolution-notes}`:
1. Backend loads the `tickets` row (with its `comments` relationship) — read only.
2. `genai_service.build_thread_transcript()` builds a plain-text transcript: subject, category, priority, status, the original description, then every **non-internal** comment as `[Customer - Name]: body` or `[Support agent - Name]: body` (internal notes are excluded from what the model sees). For draft-reply and resolution-notes, `rag_service.find_similar_resolved_tickets_safe()` also reads nearby `tickets.embedding` rows to add reference context.
3. A task-specific system prompt is prepended, and the request goes to Gemini (or Groq, if `GROQ_API_KEY` is set — text generation only, embeddings always stay on Gemini).
4. The response text is returned directly to the frontend — **it is not automatically saved as a comment**. A drafted reply has a "Use as reply draft ↑" button that copies the text into the comment textbox for the agent to review/edit before posting (which is a separate `POST /tickets/{id}/comments` call, Flow 4).

**Tables touched:** `tickets`/`comments` (read only) → `tickets.embedding` (read only, for reference context). No writes — nothing is persisted until the agent separately posts it as a real comment.

### Flow 6: Customer rates a resolved ticket

Once `ticket.status` is `resolved` or `closed`, the customer sees a star picker on the ticket page. `PUT /tickets/{id}/rating` creates the row the first time, and updates it in place on subsequent submissions ("Edit feedback"). Staff see the same rating read-only. There's no notification when a rating comes in — staff only see it by opening the ticket.

**Tables touched:** `ticket_ratings` (insert on first submission, update on every subsequent edit — one row per ticket, upsert semantics on a single endpoint).

### Flow 7: Similar tickets while working a ticket

Staff viewing any ticket automatically get `GET /tickets/{id}/similar` fired in the background. The current ticket is embedded fresh on every call (not read from its own stored `embedding` column) and compared against every **other** resolved ticket's stored `tickets.embedding` via `pgvector` cosine distance. See [full RAG section](#similar-tickets--rag-over-embeddings) below for how the matching works.

**Tables touched:** `tickets.embedding` (read only, across all resolved tickets — no writes on this flow; writing only happens at resolution time, Flow 1/3/4).

---

## ML pipeline — how classification actually works

**Training (offline, run manually):**
1. `ml/generate_dataset.py` synthesizes `data/historical_tickets.csv` from templates — each row has a `subject`, `description`, a `category` label, and a `priority` label. Crucially, priority-indicating phrases (e.g. "no rush at all" vs. "this needs immediate attention") are appended to descriptions **independent of category**, so the priority classifier has real textual signal to learn from rather than just memorizing a per-category default.
2. `ml/train.py` loads that CSV, concatenates `subject + ". " + description` into one `text` column, and trains **two independent pipelines**:
   - `TfidfVectorizer(max_features=5000, ngram_range=(1,2), stop_words="english")` → `LogisticRegression(max_iter=1000, class_weight="balanced")`
   - One pipeline for `category`, one for `priority` — completely separate models, separate `.joblib` files.
3. Each is evaluated on a held-out 20% test split (`classification_report` printed to console: precision/recall/F1 per class).
4. Artifacts saved to `backend/ml/artifacts/category_model.joblib` and `priority_model.joblib`.

**Inference (online, inside the running API):** `app/services/ml_service.py`
1. `_load_models()` lazy-loads both `.joblib` files into module-level globals the first time `predict()` is called — a one-time cost per process, not per request.
2. `predict(subject, description)` builds the same `"{subject}. {description}"` text format used in training, then calls `.predict_proba()` on both pipelines.
3. For each, it takes `argmax` of the probability vector as the predicted class, and that class's own probability as the confidence score (rounded to 4 decimals).
4. Returns `{category, category_confidence, priority, priority_confidence}` — this exact shape is what both `POST /tickets/classify` and `POST /tickets` (internally) consume.
5. `models_available()` is a cheap existence check on the two `.joblib` files, used to fail gracefully (503, or silently skip auto-classification) if training hasn't been run yet.

**Re-training:** re-run `python ml/generate_dataset.py && python ml/train.py` any time the templates change; the API picks up new models on next process restart (they're loaded once at first use, not watched for changes) — or trigger a retrain from the admin UI instead, which reloads the models in-process with no restart at all (see next section).

---

## ML feedback & active learning

Every time a human's final category/priority ends up different from what the ML model suggested, that correction is logged as a training example instead of being discarded — closing the loop between "the model was wrong" and "the model gets better."

**Capturing feedback** (`app/services/ml_feedback_service.py: record_feedback()`), called from two places in `routers/tickets.py`:
- **`create_ticket()`** — if the customer supplied an explicit `category` override that differs from the ML prediction.
- **`update_ticket()`** — if a staff member changes `category` or `priority` to something other than the ticket's `suggested_category`/`suggested_priority`.

Each call inserts one `ml_feedback` row (field, ML's original suggestion, the human's corrected value, plus a denormalized copy of the ticket's subject/description so the row stays useful even if the ticket is later edited/deleted) — unless there was nothing to learn from (no ML suggestion existed yet, or the human picked the exact same value the model already suggested), in which case it's a no-op. Priority feedback can only ever come from `update_ticket()`, since priority has no customer override at ticket creation (see [Flow 1](#flow-1-creating-a-ticket)).

**Reviewing feedback** — the `AdminMlFeedback.jsx` page (`/admin/ml-feedback`) calls `GET /admin/ml/feedback-stats` on load: total corrections, split by field, with a per-corrected-value tally so an admin can see e.g. "12 tickets were corrected to `technical_issue`."

**Retraining on demand** — clicking "Retrain models now" calls `POST /admin/ml/retrain`:
1. `ml/build_dataset_with_feedback.py: build()` reads the synthetic `data/historical_tickets.csv`, exports every `ml_feedback` row as a `{subject, description, category, priority}` row (via `ml_feedback_service.export_training_rows()` — each correction only supplies *one* of the two labels, the other is left blank), concatenates the two, and writes `data/historical_tickets_augmented.csv`.
2. `ml/train.py: train_all()` trains and evaluates both classifiers against that augmented CSV — rows with a blank label for a given classifier are dropped before fitting it, so a priority-only correction doesn't pollute the category classifier's training set with an empty label, and vice versa.
3. `ml_service.reload_models()` drops the in-process cached models, so the very next `predict()` call (the next ticket created, or the next `/tickets/classify` preview) picks up the newly retrained `.joblib` files — **no API restart required**.
4. The response — training row count, how many came from real corrections, and full per-class precision/recall/F1/support for both classifiers — is rendered directly in the admin UI (same shape `ml/train.py` prints to the console during offline training).

This is a genuine (if PoC-scale) active-learning loop: the more agents correct the model, the more signal the next retrain has, entirely from the admin panel, without touching a terminal.

---

## GenAI integration — how Gemini/Groq calls actually work

`app/services/genai_service.py` uses the `google-genai` SDK (`google.genai`), the current unified Google SDK, for text generation — and optionally Groq's OpenAI-compatible chat-completions API as a drop-in alternative for that same half. A second module, `app/services/rag_service.py`, uses the Gemini SDK's embeddings endpoint independently — see [Similar tickets](#similar-tickets--rag-over-embeddings) for that half. **Embeddings never route through Groq**, regardless of `GROQ_API_KEY` — only text generation does.

**Provider routing** (`call_model(system, user_message, max_tokens, json_mode=False, image_parts=None)`, the single entry point every text-generation call site goes through, including AI-first triage):
```python
def call_model(system, user_message, max_tokens=1024, json_mode=False, image_parts=None):
    if settings.groq_api_key:
        return _call_groq(system, user_message, max_tokens, json_mode)
    return _call_gemini(system, user_message, max_tokens, json_mode, image_parts)
```
If `GROQ_API_KEY` is set in `.env`, **every** text-generation call in the app (summarize, draft-reply, resolution-notes, and the AI-triage chatbot's replies/sentiment-scoring) goes to Groq instead of Gemini — it's an all-or-nothing switch, not per-call. Groq's chat-completions API is text-only, so `image_parts` is silently dropped on that path (screenshots just aren't sent) rather than failing the whole request over a nice-to-have.

1. `_get_client()` (Gemini path) lazily constructs a single `genai.Client(api_key=settings.gemini_api_key)`, reused across requests (module-level singleton, shared by `genai_service.py` and `rag_service.py` independently).
2. The Gemini text-generation call:
   ```python
   client.models.generate_content(
       model=settings.gemini_model,        # GEMINI_MODEL, default "gemini-3.6-flash"
       contents=[user_message, *image_parts] if image_parts else user_message,
       config=genai_types.GenerateContentConfig(
           system_instruction=system,        # task-specific instructions
           max_output_tokens=max_tokens,
           response_mime_type="application/json" if json_mode else None,
       ),
   )
   ```
   The Groq call is a plain `httpx.post` to `https://api.groq.com/openai/v1/chat/completions` with `{model, messages: [system, user], max_tokens}` and, when `json_mode=True`, `response_format: {"type": "json_object"}` — `json_mode` is what the AI-triage chatbot uses to get back strict, parseable JSON (sentiment/wants_human/resolved/reply) on either provider.
3. If neither key is usable for the active provider (`GEMINI_API_KEY` empty on the Gemini path), the call raises immediately with a clear message rather than making a doomed network call.
4. Error mapping to user-facing messages (mirrored across both providers):
   - A `429` response → a "rate limit/quota hit" message.
   - Any other client/server error → `"{Provider} API error ({code}): {message}"`.
   - Any unexpected exception (network timeout/DNS failure/etc.) → a generic `"Could not reach the {Provider} API: ..."` message — this catch-all guarantees the app itself never crashes just because the text-generation provider is unreachable.
   - All of these are raised as plain `RuntimeError`s, which the router layer catches and converts to an HTTP `502` (or, for AI-first triage, triggers the immediate-human-assignment fallback — see [AI-first triage](#ai-first-triage--how-a-new-ticket-actually-starts)).
5. Four text-generation call sites, four system prompts, mostly the same underlying transcript:
   - `summarize_ticket()` — 4-6 sentence summary, and factors in any attached screenshots. `max_tokens=1024`.
   - `draft_reply()` — full customer-facing reply, empathetic/professional tone, told explicitly not to invent facts; includes similar-past-ticket context. Accepts optional agent `instructions`. `max_tokens=1280`.
   - `generate_resolution_notes()` — internal bullet-point notes (root cause / fix / follow-up); includes similar-past-ticket context. `max_tokens=1024`.
   - `ai_triage_service._run_triage()` — the AI-first triage chatbot's turn (see [AI-first triage](#ai-first-triage--how-a-new-ticket-actually-starts)). `max_tokens=500`, `json_mode=True`.

   These budgets are deliberately generous: `gemini-3.6-flash` spends part of its output-token budget on internal "thinking" tokens before the visible answer, so a tight `max_tokens` could truncate the actual response mid-sentence on longer threads.

**Screenshots as context** (`_collect_image_parts()`, Gemini only): for `summarize_ticket()`, `draft_reply()`, and `generate_resolution_notes()`, up to `MAX_IMAGE_ATTACHMENTS` (4) image attachments — from the ticket itself or any non-internal reply — are read off disk and passed to Gemini as `Part.from_bytes(...)`, so the model can actually see what a customer attached (e.g. an error screenshot) instead of an agent having to describe it in words. A file missing from disk is silently skipped. `TicketDetail.jsx` shows the agent how many screenshots the assistant is currently looking at ("· sees 2 screenshots").

**What the model actually sees** (via `build_thread_transcript()`): subject, category, priority, status, the customer's original description, then the non-internal comment thread in order — internal notes are filtered out, so agent-only context never leaks into a customer-facing draft reply. For draft-reply, resolution-notes, and AI-triage, `build_similar_context()` also appends up to 3 similar past resolved tickets (via `rag_service.find_similar_resolved_tickets_safe()`) as reference material, explicitly instructed to be used "only if genuinely relevant."

---

## SLA engine — every state transition

`app/services/sla.py` — all times are UTC, computed against `datetime.utcnow()`.

| Trigger | Function | What happens |
|---|---|---|
| A ticket gets a priority for the first time | `create_sla_history_for_ticket()` | Looks up the `SLAPolicy` for that priority, creates one `SLAHistory` row: `response_due_at = now + response_time_hours`, `resolution_due_at = now + resolution_time_hours`. One-time — enforced by `sla_history.ticket_id` being unique. |
| First non-internal comment from an agent/admin | `record_first_response()` | No-op if already stamped — idempotent. Otherwise stamps `first_response_at = now` and sets `response_breached = now > response_due_at` **at that moment**. |
| Status set to `resolved` for the first time | `record_resolution()` | No-op if already stamped. Otherwise stamps `resolved_at = now` and sets `resolution_breached = now > resolution_due_at`. |
| Every time a ticket is read (list or detail) | `refresh_breach_flags()` | Recomputes breach flags **without writing to the DB** — if a ticket is still waiting on a first response and `now > response_due_at`, it reports `response_breached = True` live, even though no event has happened yet to persist that flag. This is why an ignored, overdue ticket shows "breached" immediately, not only after someone eventually touches it. |
| Every `SLA_BREACH_SWEEP_INTERVAL_SECONDS` (60s), regardless of whether anyone is looking | `find_newly_breached()` (called from a background task in `main.py`) | The **only** path that writes a breach flag *and* announces it proactively — see below. |

**Why two breach-flag paths (write-on-event vs. compute-on-read)?** Once an event happens, breach state is a historical fact and gets persisted permanently. Before that event, breach state is a function of the current time and can't be known in advance — so it's recomputed fresh on every read instead of relying on a background job/cron for the *display* value.

**Proactive breach notification** (`main.py: _sla_breach_sweep_loop()`, `services/sla.py: find_newly_breached()`): the read-on-view behavior above only surfaces a breach to someone who happens to open that exact ticket. A background `asyncio` task, started at app startup and running forever on the same event loop the WebSocket manager uses, closes that gap:
1. Every 60 seconds, it queries every `open`/`in_progress` ticket whose `sla_history` has a response or resolution deadline that has passed **and** hasn't been notified yet (`response_breach_notified`/`resolution_breach_notified` still `False`).
2. For each newly-crossed clock, it sets the corresponding `*_breached` and `*_breach_notified` flags (so the same breach is never re-announced on a later sweep) and commits.
3. It broadcasts an `sla.breached` WebSocket event — `{ticket_id, subject, breach_type: "response" | "resolution", assigned_agent_id}` — to that ticket's room *and* the admin room.
4. `AppShell.jsx` listens for `sla.breached` on the site-wide admin socket (not just on `AdminMonitor.jsx`) and pops a dismissible toast from wherever an admin happens to be in the app, that navigates to the ticket on click and refreshes the sidebar's breach counter. This is the one event type in the app that has no corresponding REST trigger — it only ever comes from this sweep.

**Frontend presentation** (`frontend/src/utils/sla.js`, `frontend/src/pages/TicketDetail.jsx`'s `SLARing`, `frontend/src/components/Badges.jsx`'s `SLABadge`): the raw flags above are turned into a ring/progress display plus a one-line plain-language headline (🟢 On track / ⚠️ At risk / 🔴 Overdue) both on the ticket detail page and as a compact colored badge in the ticket list — purely presentational, derived from the same `response_breached`/`resolution_breached`/due-at fields, never re-deciding breach state itself.

---

## Real-time updates — WebSockets

Two pieces make this work: `app/ws_manager.py` (server-side connection registry + broadcaster) and `frontend/src/hooks/useWebSocket.js` (client-side reconnecting hook).

**Server side (`ws_manager.py`):**
- In-memory only — **not** shared across multiple processes/workers; fine for a single-process dev/demo deployment, but a broadcast only reaches sockets held by the same process it originated in.
- `ticket_rooms`: one room per ticket ID, tracking each connected socket alongside the viewer's role (so internal-note events can be withheld from customer sockets in that same room).
- `admin_room`: a separate room joined only by admin sockets, which receives *every* event system-wide (used to drive the live "all tickets" dashboard).
- Broadcasting from a synchronous route handler (most of them, since FastAPI runs plain `def` handlers in a thread pool) works via `asyncio.run_coroutine_threadsafe` against the event loop captured at app startup.
- Dead sockets are dropped silently on a failed send — best-effort delivery, no retry/ack/queueing.

**Routes (`app/routers/ws.py`):**
- `WS /ws/tickets/{id}?token=<jwt>` — join a single ticket's room. Closes `4401`/`4403` on bad auth or no access. The client never sends messages; the socket just stays open to receive pushes (the server reads incoming frames purely to detect disconnects).
- `WS /ws/admin?token=<jwt>` — admin-only, joins the shared admin room.

**Events broadcast:**

| Event `type` | Trigger | Rooms | Staff-only? |
|---|---|---|---|
| `ticket.created` | `POST /tickets` | ticket room + admin | no |
| `ticket.updated` | `PATCH /tickets/{id}`, or `POST /tickets/{id}/ai/reassign` | ticket room + admin | no |
| `comment.created` | `POST /tickets/{id}/comments`, or an AI-triage/reassignment-notice comment | ticket room + admin | yes, if the comment is an internal note |
| `agent.availability_changed` | `PATCH /auth/me/availability` | admin room only | no |
| `sla.breached` | The background SLA sweep in `main.py` (not a REST call — see [SLA engine](#sla-engine--every-state-transition)) | ticket room + admin | no |

Rating submissions do **not** broadcast anything — staff must reload the ticket to see a new rating.

**Client side:** `useWebSocket(path, onMessage, enabled, onStatusChange)` opens `ws://localhost:8000{path}?token=...`, reconnects on a fixed 2-second backoff if the connection drops, and reports connect/disconnect status (rendered by the small `LiveDot` component). Used in four places:
- `TicketDetail.jsx` — `/ws/tickets/{id}` — live-appends new comments and merges field updates into the open ticket view.
- `TicketList.jsx` — `/ws/admin`, admins only — live-prepends new tickets and merges updates into the table.
- `AdminMonitor.jsx` — `/ws/admin`, always on (admin-only page) — drives the "Live Conversations" dashboard: ticket list, last-message previews, and agent availability dots, with a brief highlight flash on the row that just changed.
- `AppShell.jsx` — `/ws/admin`, admins only, mounted once for the whole logged-in app (not tied to any one page) — listens for `sla.breached` and pops a toast from wherever the admin currently is, plus refreshes the sidebar's ticket/breach counters on every route change.

---

## Agent availability & AI ticket assignment

**Availability** (`User.availability`, enum `online`/`busy`/`offline`): agents/admins self-report their status via a 3-button toggle in the sidebar (`PATCH /auth/me/availability`). It's purely informational for humans *and* an input to the assignment algorithm below. Changing it broadcasts `agent.availability_changed` to the admin WebSocket room, so `AdminMonitor.jsx` updates its availability dots live without a refresh.

**Assignment algorithm** (`app/services/assignment_service.py`), run automatically on ticket creation and on-demand via `POST /tickets/{id}/ai/reassign` (admin-only):

1. Candidate pool is every **active `agent`-role** user (admins are deliberately excluded from the auto-assignment pool — an admin can still be assigned *manually*, but the AI algorithm won't pick one).
2. Candidates are bucketed by availability: `online`, `busy`, everyone else. The algorithm uses the **first non-empty bucket, in that order** — i.e. it strictly prefers any online agent over any busy agent, regardless of load, and only falls back to offline agents if literally nobody is online or busy.
3. Within the chosen bucket, it picks whoever currently has the **fewest active tickets** (`open` + `in_progress` count, computed fresh each time — not cached). Ties fall to whichever agent the query happens to return first (effectively arbitrary).
4. If there are no active agents at all, the ticket is explicitly set to `assignment_source = unassigned` with an explanatory note, rather than being left in an ambiguous state.
5. The resulting note is human-readable, e.g. *"Auto-assigned to Mark (online) — 2 active tickets at time of assignment."* — the load number is a snapshot at assignment time, not a live count.

**Manual assignment** is a separate, admin-only path (`PATCH /tickets/{id}` with `assigned_agent_id`) that can target an `agent` **or** `admin` (broader than the auto-assign pool), and sets `assignment_source = admin`.

The ticket detail page shows a small pill next to the assignee — "✨ AI assigned" / "👤 Manual" / "🚨 Escalated by AI" / "Unassigned" — so it's always visible at a glance whether, and how, a human ended up owning the ticket.

---

## AI-first triage — how a new ticket actually starts

`app/services/ai_triage_service.py`. A new ticket does **not** go straight to a human agent — it starts in the AI's hands, and a human only gets involved once the AI escalates (or fails). This is the system's headline behavior; the rest of this section is `ai_triage_service.py` read top to bottom.

**The AI Assistant "user."** All AI-authored comments are attributed to a real `users` row, lazily created the first time it's needed (`_get_bot_user()`): name "AI Assistant", email `ai-assistant@system.internal`, role `admin` (so it isn't subject to the same visibility restrictions a plain agent row would be), `is_active = False` (so `GET /agents` — the assignment picker — never offers it as an assignable agent, and it can never log in). Its password hash is a random 32-byte token nobody knows.

**On ticket creation** (`handle_new_ticket()`, called from `create_ticket()` right after the SLA clock starts):
1. `tickets.handling_mode` is set to `'ai'`.
2. `_run_triage()` builds the ticket transcript (+ up to 3 similar past resolved tickets as reference context) and calls the model (Gemini or Groq, `json_mode=True`) with a system prompt instructing it to reply with strict JSON: `{sentiment, wants_human, resolved, reply}`.
3. The AI's `reply` is inserted as a `comments` row (author = the AI Assistant, `is_ai_generated = True`), and that comment stamps `sla_history.first_response_at` — **the AI's own reply counts as the ticket's first response**, same as a human's would.
4. The AI always gets this first attempt regardless of tone — `handle_new_ticket()` never escalates on the very first message, even if the customer's initial description already reads as angry.
5. If the AI judged the issue `resolved` (and didn't also flag `wants_human`), the ticket is immediately resolved: status → `resolved`, `resolved_at` stamped, SLA resolution recorded, and the ticket embedded for future similar-tickets search — **entirely without a human ever touching it**.
6. **Fallback:** if the model call itself raises (`RuntimeError` — GenAI unreachable/unconfigured), `create_ticket()` catches it, sets `handling_mode` back to `'human'`, and runs `assignment_service.auto_assign()` immediately instead — the old, pre-AI-triage behavior — so a ticket never sits with no owner and no attempt made just because GenAI happened to be down at that moment.

**On every subsequent customer reply, while still AI-handled** (`handle_customer_message()`, called from `POST /tickets/{id}/comments` whenever the author is the customer, `handling_mode` is still `'ai'`, and the ticket isn't resolved/closed):
1. Re-runs the same triage call against the now-longer transcript.
2. Stamps the **customer's own comment** with `sentiment` (`angry`/`frustrated`/`neutral`/`satisfied`) — this is the only path that ever sets `comments.sentiment`.
3. If the sentiment is negative (`angry`/`frustrated`) or the AI flagged `wants_human`, `tickets.dissatisfaction_count` increments.
4. **Below `AI_ESCALATION_THRESHOLD`** (default 2): the AI just replies again (another AI-authored comment), and resolves the ticket if it judges the issue solved — same as step 5 above.
5. **At/above the threshold** (`_escalate()`): `assignment_service.auto_assign()` picks a human agent (`assignment_source = ai_escalation`, with a note naming the reason — "the customer asked to speak with a human agent" or "the customer stayed dissatisfied across multiple replies"); `handling_mode` → `'human'` and `escalated_at` is stamped; a customer-visible handoff comment is posted ("I've connected you with {agent} from our support team…"); and, best-effort, `genai_service.summarize_ticket()` generates an **internal** handoff-summary comment (`is_internal_note = True`) so the agent isn't starting cold — if that summary call itself fails, the escalation still succeeds, it just skips the summary.
6. If the triage call raises at any point here, `add_comment()` in `routers/tickets.py` swallows the `RuntimeError` — the customer's message is still saved, it just sits without an AI reply until GenAI is reachable again or a human/the customer acts.

**What always ends AI-handling, independent of the threshold:**
- Any staff member posting a non-internal reply (`add_comment()` flips `handling_mode` to `'human'` unconditionally the moment that happens).
- A manual reassignment by an admin (`PATCH /tickets/{id}` with `assigned_agent_id`) — always forces `handling_mode = 'human'`, even if the new assignee is the same agent the AI would have escalated to.
- An admin clicking "✨ Auto-assign" (`POST /tickets/{id}/ai/reassign`) — same effect, on demand.

Each of these three paths that changes *who* is handling a ticket away from the AI also posts a customer-visible reassignment notice via the shared `post_reassignment_notice()` helper, so the customer always sees an explicit "reassigned from X to Y" message rather than the ownership silently changing underneath them.

**Where this shows up in the UI:** `TicketDetail.jsx`'s "Assigned" row shows "🤖 AI Assistant is handling this" while `handling_mode === 'ai'` and there's no `assigned_agent_id` yet; `TicketList.jsx` and `AdminMonitor.jsx` show "🤖 AI handling" in the agent column the same way. Every customer message during the AI phase gets a small sentiment chip (😠/😕/😐/🙂) next to it in the thread.

---

## File attachments

`app/routers/attachments.py`, storage on local disk under `UPLOAD_DIR` (default `backend/uploads/`, git-ignored, created automatically on startup).

**Validation (server-side, not just the frontend's `accept` hint):**
- Allowed MIME types only: PNG, JPEG, GIF, WebP, PDF, and `.docx` — matched by exact `Content-Type` string, not by sniffing file contents or checking the extension.
- Size limit: `MAX_UPLOAD_SIZE_MB` (default 10 MB) per file, enforced after reading the upload.
- Empty (0-byte) files are rejected.
- A customer cannot add attachments to a `closed` ticket (mirrors the rule that blocks closed-ticket replies).

**Storage:** each file is saved under a random `uuid4().hex` + original extension (`stored_name`) — the original filename is kept only in the database (`filename`) for display and download, never used as the on-disk path, which avoids collisions and path-traversal risk.

**Attachment targets:** an attachment can belong to the ticket itself (`comment_id = null` — e.g. uploaded at ticket-creation time, or added standalone afterward) or to one specific reply (`comment_id` set — uploaded alongside a comment). The frontend renders ticket-level attachments above the comment thread and reply-level ones inline inside that reply's bubble.

**Download & delete:** `GET /attachments/{id}/download` streams the file back with its original filename and content type, gated by the same `assert_can_view` rule as the parent ticket. `DELETE /attachments/{id}` (uploader or admin only) removes both the disk file and the DB row.

**Known gap:** if a multi-file upload request fails validation partway through (e.g. file 3 of 5 is oversized), files already validated and written to disk earlier in that same request are **not** cleaned up, since nothing is committed to the database until the whole batch succeeds — a minor orphaned-file possibility, not a data-integrity issue (nothing references the orphan).

---

## Similar tickets — RAG over embeddings

`app/services/rag_service.py` — helps an agent reuse how a similar problem was solved before, by searching **past resolved tickets** semantically rather than by keyword.

**Storing an embedding (write path):** the moment a ticket is resolved for the first time (`PATCH /tickets/{id}` with `status: resolved`), `embed_and_store_ticket()` runs:
1. Builds one block of text: subject + description + every **non-internal** comment (internal notes are excluded, same rule as GenAI transcripts).
2. Calls Gemini's embedding endpoint (`GEMINI_EMBEDDING_MODEL`, default `gemini-embedding-001`) with `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality=768`.
3. Stores the resulting vector in `tickets.embedding` (a `pgvector` column) and stamps `embedding_updated_at`.
4. **Failure is silently swallowed** — if Gemini is unreachable or misconfigured at that exact moment, the ticket still resolves normally, it just has no embedding until the backfill script is run.

Open/in-progress tickets never get a stored embedding — only resolved ones are indexed, since the whole point is "how was this kind of problem solved."

**Querying (read path):** `GET /tickets/{id}/similar?top_k=5` (staff only):
1. Embeds the *current* ticket fresh, on the spot, with `task_type="RETRIEVAL_QUERY"` (a different task type than storage — asymmetric embeddings, which is the standard pattern for retrieval-style embedding models — the query is not simply matched against its own stored form).
2. Runs a `pgvector` cosine-distance nearest-neighbor query against all resolved tickets that have a stored embedding (excluding the current ticket itself).
3. Returns up to `top_k` results (1–20, default 5) with `similarity = 1 - cosine_distance`, plus a 220-character snippet of the description.
4. Each result carries a `viewable` flag: `true` for admins or for the requesting agent's own assigned tickets, `false` otherwise. A non-viewable result still shows its subject/snippet/similarity (useful context even from a ticket you can't open), but the frontend renders it as a plain, non-clickable row instead of a link — so an agent can't use "similar tickets" as a backdoor into a colleague's ticket.

**Backfilling:** `backend/app/backfill_embeddings.py` is a standalone script to generate embeddings for resolved tickets that predate this feature (or that failed silently at resolution time) — see [Setup](#setup).

---

## Canned responses

`app/routers/canned_responses.py` + the "Manage" modal and "Suggested for this ticket" chips on the ticket detail page's reply composer.

Any staff member can create a reusable reply template (title, body, optional free-text category tag). Templates appear two ways on `TicketDetail.jsx`:
- A plain **"Insert canned response…" dropdown** listing every template alphabetically — selecting one appends its body into the compose textarea, which the agent can still edit before posting.
- **"Suggested for this ticket"** chips, populated from `GET /canned-responses/suggest?ticket_id=...&top_k=3` — the same semantic-similarity machinery as [similar tickets](#similar-tickets--rag-over-embeddings), but comparing the current ticket's embedding against each canned response's own embedding (of `"{title}. {body}"`) instead of against other tickets. Each template is embedded automatically on create/edit (`_embed_canned_response()`, best-effort — a Gemini hiccup just means it won't rank in `/suggest` until the next successful save, never blocks saving the template itself). If no embeddings are available yet, `/suggest` falls back to a plain alphabetical list with `similarity: 0`.

Only the original creator or an admin can edit or delete a given template (`_assert_can_modify`), so anyone can contribute reusable text but people can't tamper with each other's.

---

## Analytics dashboard

`app/routers/analytics.py` + `AdminAnalytics.jsx` (`/admin/analytics`, admin-only). A single-page read-only rollup of metrics that are already tracked elsewhere in the app — nothing here is a separate data pipeline, it's all live queries against `tickets`, `comments`, `sla_history`, and `ticket_ratings`.

One call, `GET /admin/analytics/overview`, returns everything the page needs:
- **Ticket volume** — daily ticket counts for the last 30 days (`VOLUME_WINDOW_DAYS`), rendered as a line/area chart.
- **Category distribution** — ticket count per category, rendered as horizontal bars.
- **Sentiment breakdown** — comment count per AI-detected sentiment (`angry`/`frustrated`/`neutral`/`satisfied`) — necessarily sparse, since `comments.sentiment` is only ever set on a customer message during the [AI-first triage](#ai-first-triage--how-a-new-ticket-actually-starts) phase, never for staff replies or post-escalation messages.
- **SLA compliance** — response and resolution met-vs-breached counts, recomputed live via `refresh_breach_flags()` for every `sla_history` row (so an ignored, still-ticking clock isn't miscounted as "met" just because nothing has stamped it yet) — rendered as two stacked bars with a "% met" summary.
- **CSAT** — the average star rating and total rating count across every `ticket_ratings` row.

Everything is computed fresh on every page load (`useEffect` → one `GET` on mount) — there's no caching layer, no scheduled aggregation job, and no date-range picker (the 30-day window is fixed server-side). The charts themselves are hand-rolled inline SVG (no charting library) in `AdminAnalytics.jsx`.

---

## Admin features

Four admin-only pages, all client-guarded in `App.jsx` (redirect to `/` for non-admins) and backed by server-side `require_admin`/`require_staff` checks on the underlying data — the frontend guard is convenience, not the security boundary.

**`AdminUsers.jsx` (`/admin/users`) — staff account management:**
- Create an `agent` or `admin` account (name/email/password/role) via `POST /admin/users`.
- List every user (including customers, read-only for them) via `GET /admin/users`.
- Change a staff member's role, or activate/deactivate their account, via `PATCH /admin/users/{id}` — both actions are disabled in the UI (and rejected server-side, 400) for the currently logged-in admin's own row, so an admin can't accidentally lock themselves out.

**`AdminMonitor.jsx` (`/admin/monitor`) — "Live Conversations":**
- A real-time dashboard of every open/in-progress ticket system-wide: last-message preview per ticket, assigned agent with a live availability dot, click-through to any ticket.
- Initial load via `GET /tickets` + `GET /agents`; kept live afterward purely by the `/ws/admin` WebSocket connection (`ticket.created`/`ticket.updated`/`comment.created`/`agent.availability_changed`/`sla.breached` events), including a brief highlight "flash" on whichever row just changed.

**`AdminAnalytics.jsx` (`/admin/analytics`) — see [Analytics dashboard](#analytics-dashboard) above** for the full breakdown: ticket volume, category mix, sentiment, SLA compliance, and CSAT, all from one `GET /admin/analytics/overview` call.

**`AdminMlFeedback.jsx` (`/admin/ml-feedback`) — see [ML feedback & active learning](#ml-feedback--active-learning) above** for the full breakdown: correction stats from `GET /admin/ml/feedback-stats`, and a "Retrain models now" button that calls `POST /admin/ml/retrain` and renders the resulting per-class metrics for both classifiers.

---

## Frontend — pages, routing, state

**Entry point:** `main.jsx` mounts `<App>` inside `<BrowserRouter>` and `<AuthProvider>` (global auth context, no Redux/Zustand — just React context + local component state throughout).

**Routing (`App.jsx`):** there's no separate `PrivateRoute` wrapper component — `App.jsx` branches on whether `user` is set and renders one of two route tables:

Not logged in:

| Path | Component |
|---|---|
| `/login` | `Login` |
| `/register` | `Register` |
| `/forgot-password` | `ForgotPassword` |
| `/reset-password` | `ResetPassword` (reads `?token=` from the URL) |
| `*` | redirect → `/login` |

Logged in (wrapped in `AppShell`):

| Path | Component | Guard |
|---|---|---|
| `/` | `TicketList` | any logged-in user (supports `?sla=breach` to pre-filter to breaching tickets — see below) |
| `/new` | `NewTicket` | any logged-in user |
| `/tickets/:id` | `TicketDetail` | any logged-in user (per-ticket 403 enforced server-side) |
| `/admin/users` | `AdminUsers` | client-side redirect to `/` if not admin |
| `/admin/monitor` | `AdminMonitor` | client-side redirect to `/` if not admin |
| `/admin/analytics` | `AdminAnalytics` | client-side redirect to `/` if not admin |
| `/admin/ml-feedback` | `AdminMlFeedback` | client-side redirect to `/` if not admin |
| `*` | redirect → `/` | |

**State management pattern:** every page owns its own `useState`/`useEffect` data fetching directly against the `api` axios instance — no global cache/query library. Any REST mutation is followed by an explicit refetch rather than an optimistic local update; live updates instead arrive via the WebSocket hook where wired up (ticket detail, ticket list for admins, admin monitor, and the site-wide `AppShell` listener for SLA-breach toasts).

**`AppShell.jsx`** wraps every logged-in route: it renders `Sidebar` + a breadcrumb bar derived from the current path (`crumbFor()`), refetches `GET /tickets` on every route change to keep the sidebar's total/breach counts current, and — independent of whatever page is open — keeps one `/ws/admin` connection alive (admins only) purely to catch `sla.breached` events and pop a dismissible toast that deep-links to the affected ticket. This is why an admin can be handed a breach notification even while sitting on `/admin/users`, not just while watching the relevant ticket.

**Role-aware rendering:** the same components branch on `user.role` rather than having separate customer/staff apps:
- `Sidebar`: customers see "My Tickets" + "New Ticket"; staff see "All Tickets" plus an "SLA Breaches" alert link (`/?sla=breach`, with a live breach count badge); admins additionally see "Live Conversations," "Analytics," "Manage Users," and "Model Feedback." The availability toggle only renders for staff.
- `TicketList`: staff get extra columns and an "assigned to me" filter; customers get a "+ New Ticket" button instead; the `?sla=breach` query param (set by the Sidebar's alert link) filters the table client-side to tickets `slaInfo(ticket).state === 'breach'`, with a "Clear filter" notice shown above the table.
- `TicketDetail`: the "Manage ticket" panel, internal-note checkbox, GenAI assistant panel, canned-responses manager (incl. semantic suggestion chips), and similar-tickets card are all staff-only, computed client-side (`isStaff`) — **the server independently enforces the same restrictions**, so this is UX convenience, not the security boundary. The manual agent-assignment dropdown and "✨ Auto-assign" button are further restricted to admins only.

**`Badges.jsx`** — small pure-display components: `StatusBadge`, `PriorityBar`, `SLABadge` (the latter shows a colored dot + remaining time or breach state, derived from `utils/sla.js`).

**Loading states:** every page-level fetch renders a shared `.loading-state` block (spinner + label) instead of plain text while its data is in flight.

---

## Visual design system

All styling lives in one file, `frontend/src/index.css` — there's no CSS-in-JS or utility framework (no Tailwind/styled-components); components apply plain class names and everything is themed through a small set of CSS custom properties declared once on `:root`:

- **Tokens:** `--color-*`-style variables (surface/text/border/primary/danger/success/warning), `--r-sm/md/lg/xl` radii, `--sh-sm/md/lg` shadows, and a shared `--ease` transition curve — changing the look means editing one variable, not hunting through every component's styles.
- **Typography:** Google Fonts' Inter, loaded via `<link>` in `index.html` (falls back to the system font stack if it fails to load).
- **Branding:** a small gradient "S" mark (`.brand-mark`) in the sidebar and on the login/register pages.
- **Form controls:** native `<select>` elements get a custom chevron instead of the OS default arrow; inputs/selects/textareas share one focus style (a soft box-shadow ring).
- **Motion:** `.card` elements fade/slide in on mount; a shared `.spinner` backs every loading state; the SLA ring animates its fill via `stroke-dashoffset` transitions.
- **SLA panel:** a dark, high-contrast card (`.sla-panel`) distinct from the rest of the light UI, with a progress ring, a plain-language colored headline (🟢/⚠️/🔴), and the underlying response/resolution/policy detail below it.
- **Live indicator:** `LiveDot` renders a small pulsing/static dot reflecting WebSocket connection status wherever it's used.
- **Auth pages:** `Login`/`Register`/`ForgotPassword`/`ResetPassword` share an `.auth-shell` centered layout with a subtle two-tone radial-gradient background.

None of this touches data-fetching or business logic; it's presentation-only, layered on top of the component structure described above.

---

## Known POC shortcuts (intentional)

- No automated tests, per the assignment.
- No Alembic migrations — tables are created via `Base.metadata.create_all`.
- No rate limiting anywhere, including on `/auth/forgot-password` (it can be hit repeatedly).
- No refresh-token flow — an expired JWT just means logging in again.
- Password reset "emails" are printed to the server console, not actually sent — there's no email/SMS provider wired in.
- The ML dataset is synthetic, not real ticket history.
- File attachments are stored on local disk, not object storage — doesn't scale past a single machine/deployment, and a failed multi-file upload can leave an orphaned file on disk (see [File attachments](#file-attachments)).
- WebSocket state (`ws_manager.py`) is in-memory and single-process — broadcasts don't fan out across multiple backend workers/instances.
- A resolved ticket's embedding can silently fail to generate (Gemini down/misconfigured) with no automatic retry — only the manual backfill script catches up on it.
- SLA breach notification is push-in-app only (a WebSocket toast to admins, via the background sweep in `main.py`) — there's no email/SMS/Slack alert, and the sweep only reaches admins who currently have the app open in a browser tab; nobody is paged if the whole team is logged out.
- The retrain endpoint (`POST /admin/ml/retrain`) runs synchronously, in-request, on the same process serving live traffic — fine at this dataset's PoC scale (a few thousand rows), but a much larger training set would need to move to a background job so it doesn't block the API worker for the duration of training.
- Analytics (`GET /admin/analytics/overview`) recomputes every metric from scratch on every request — fine at this data volume, but there's no caching/materialized-view layer, so it wouldn't scale to a very large `tickets`/`comments` table without added latency.
- If you're upgrading an existing database created before the `urgent`→`critical` priority rename, you must rename that row manually (`UPDATE priorities SET name = 'critical' WHERE name = 'urgent';`) — the seed script only inserts missing rows, it doesn't rename existing ones. A fresh database seeded from scratch doesn't need this.
- If you're upgrading a database from before the AI-first-triage / ML-feedback / analytics features existed, `ensure_schema_migrations()` (see [Database schema](#database-schema--every-table-column-and-relationship)) backfills the new columns automatically at startup — but the new `ml_feedback` *table* is created by `Base.metadata.create_all()`, which only adds missing tables, so no manual step is needed there either. There is genuinely nothing to do by hand beyond the priority-rename case above.
