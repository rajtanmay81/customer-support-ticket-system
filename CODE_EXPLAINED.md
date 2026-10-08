# Customer Support Ticket System — Code Walkthrough

A plain-English guide to what this project does, how it's built, and how the
pieces fit together — written so you can explain it in a meeting. For the
exhaustive technical reference (every column, every endpoint), see
[README.md](README.md); this document is the "walk someone through it"
version. For a short, non-technical summary written for a manager, see
[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).

---

## 1. What this project is, in one paragraph

It's a helpdesk web app. A customer submits a support ticket, and an **AI
assistant answers it first** — not a person — using the ticket's own text
plus how similar problems were solved before; it tries to actually resolve
the issue, and only escalates to a human once the customer is frustrated or
explicitly asks for one. In parallel, the system automatically guesses the
ticket's **category** (billing, technical issue, etc.) and **priority**
(low/medium/high/critical) using a machine-learning model trained on past
ticket text — and that model gets better over time, since every human
correction is logged and can be folded back into a retrain with one click.
That priority starts an **SLA clock** (a deadline for first response and
resolution), which proactively alerts admins the moment it's actually
breached, not just whenever someone happens to look. When a ticket does
reach a human, agents work it — reply, add internal notes, attach files,
change status — leaning on a **GenAI assistant** (Google Gemini, or Groq as
a swappable alternative) to summarize a thread, draft a customer reply, or
write resolution notes, and on a **"similar tickets" search** and
**semantically-ranked canned responses** that surface how comparable
problems were solved before. Everyone watching a ticket sees changes
**live**, over a WebSocket connection, without refreshing, and admins get a
live analytics dashboard on top of all of it. It's a proof of concept built
to demonstrate the full pattern end to end, not a production system (see
[§8](#8-what-this-is-not-poc-shortcuts)).

## 2. The six "smart" pieces, and why they exist

| Piece | Problem it solves | How |
|---|---|---|
| **AI-first triage chatbot** | Every ticket historically waits for a human, even the trivial ones. | An AI agent replies to a new ticket directly, using the ticket text and similar past resolved tickets as context, and tries to resolve it itself. Every subsequent customer message is scored for sentiment and for an explicit request for a human; enough negative signal (configurable threshold) auto-escalates to a human agent with an AI-written handoff summary. |
| **ML classifier, with active learning** | Every ticket needs a category + priority so it can be routed and given a deadline. Doing this by hand is slow and inconsistent, and a static model goes stale. | Two small models (trained offline on a labeled dataset) read the ticket text and predict both fields, with a confidence score. Runs in-process, no network call, instant. Every time a human overrides a suggestion, the correction is logged; an admin can trigger a retrain from the UI that folds those corrections back in and hot-swaps the live model — no restart. |
| **SLA engine** | Support teams promise response/resolution times per priority. Someone needs to track whether that promise was kept — and notice the moment it's broken, not eventually. | The moment a ticket's priority is known, a deadline pair is computed and stored. The system stamps facts as they happen (first reply, resolution) and, for anything still pending, computes "are we late?" live every time the ticket is viewed. A background check every 60 seconds also proactively pushes a live alert to admins the instant a clock actually runs out. |
| **AI ticket assignment** | New tickets (or AI escalations) need an owner immediately, ideally whoever's actually free. | A small algorithm ranks active agents by availability (online > busy > offline) and picks whoever, within that tier, currently has the fewest open tickets. Runs automatically on every escalation; an admin can also re-run it on demand. |
| **GenAI assistant** | Writing a summary, a reply, or resolution notes from a long comment thread is repetitive agent work. | A service builds a plain-text transcript of the ticket (plus any attached screenshots) and sends it to Gemini (or Groq) with a task-specific instruction. The agent reviews/edits before anything is actually sent — the AI never posts on its own once a ticket is human-handled. |
| **"Similar tickets" & canned-response search (RAG)** | When a new problem looks like one seen before, an agent shouldn't have to remember or search by exact keyword. | Once a ticket is resolved, its text is converted into a numeric "embedding" (via Gemini) and stored; canned-response templates are embedded the same way. When working a new ticket, the system embeds it too and finds the closest matching past tickets *and* the most relevant canned responses by meaning, not keyword — powered by Postgres's `pgvector` extension. |

## 3. Architecture at a glance

```
Browser (React)  ──HTTP + JWT──▶  FastAPI backend  ──▶  PostgreSQL + pgvector (tickets, users, comments, SLA, embeddings,
        ▲                              │                ml_feedback)
        │                              ├──▶  ML models (.joblib files loaded into memory)
        └──── WebSocket (live push) ───┤
                                        ├──▶  Gemini (embeddings always; text generation unless GROQ_API_KEY is set)
                                        ├──▶  Groq (text generation only, optional swap-in for Gemini)
                                        └──▶  Local disk (file attachments)
```

The frontend never talks to the database, the ML models, Gemini, or the
filesystem directly — everything is mediated by one backend, which is the
single point of authorization and business logic. This matters for the "why
is this secure" question: a customer's browser has no path to internal
notes, other customers' tickets, or other agents' tickets except through
backend checks — and the same checks apply whether the request comes in
over normal HTTP or over a WebSocket connection.

## 4. Tech stack (and why each piece was picked)

| Layer | Choice | Why it's a reasonable pick for this |
|---|---|---|
| API | FastAPI (Python) | Fast to build, auto-generates interactive API docs (`/docs`), plays well with the ML/GenAI stack since it's already Python, and has first-class WebSocket support built in. |
| Database | PostgreSQL + SQLAlchemy + `pgvector` | Relational data (tickets ↔ users ↔ comments ↔ SLA) is a natural fit for a relational DB; `pgvector` adds similarity search on top without needing a separate vector database. |
| Auth | JWT (signed tokens) + bcrypt | Standard stateless auth — no server-side session store needed. Deactivation is still enforced live by re-checking the user row on every request. |
| Real-time | Raw WebSockets (FastAPI built-in) | No extra infrastructure (no Redis/Socket.IO) needed for a single-process demo; a small in-memory "who's watching what" registry is enough. |
| ML | scikit-learn (TF-IDF + Logistic Regression) | Deliberately simple/interpretable — enough to prove the classification pattern without needing a training cluster. |
| GenAI | Google Gemini via `google-genai` SDK, with Groq as an optional swap-in | Gemini handles both text generation (AI triage/summaries/drafts) and embeddings (similar tickets, canned responses) through one SDK. If `GROQ_API_KEY` is set, text generation alone routes to Groq's OpenAI-compatible chat API instead — embeddings always stay on Gemini. Isolated in two small service modules either way. |
| File storage | Local disk | Simplest possible option for a POC; the code isolates this behind one router so swapping in S3-style storage later would be a contained change. |
| Frontend | React (Vite) + plain `axios` | No heavyweight state library — every page fetches its own data, topped up with live WebSocket pushes where it matters. Simple to reason about for a project this size. |

## 5. How a ticket actually moves through the system

This is the core story — the sequence of events from "customer has a
problem" to "ticket resolved and rated." The headline thing to understand:
**a new ticket starts with the AI, not a human.**

**Step 1 — Customer creates a ticket.**
`NewTicket.jsx` → `POST /tickets`, with optional file attachments. The
customer can optionally click "Suggest category & priority (AI)" first,
which calls `POST /tickets/classify` — a live preview that runs the ML
model but doesn't save anything. On actual submit, the backend
([tickets.py](backend/app/routers/tickets.py) → `create_ticket`)
**always** runs the ML prediction (for visibility, even if the customer
picked their own category) and stores both: the official field and the raw
model guess in separate columns (and, if the customer's choice disagreed
with the model, logs that as ML feedback — see §7). If a priority ends up
set, the SLA clock starts immediately. A `ticket.created` event is pushed
live to anyone watching (the ticket's own room, and any admin watching
everything).

**Step 2 — The AI takes the first attempt, not a human.**
Right after the SLA clock starts, `ai_triage_service.handle_new_ticket()`
runs: the ticket flips into `handling_mode: 'ai'`, and an AI Assistant
"user" (a real but unloginnable `users` row) reads the ticket and posts an
actual reply in the thread — not a canned acknowledgment, a real attempt at
the issue, informed by similar past resolved tickets. That reply also
counts as the SLA's "first response." If the AI believes it solved the
problem, it resolves the ticket itself, right there, with no human
involved at all. **Only if GenAI is unreachable/unconfigured** does the
system fall back to the old behavior — assign a human immediately via the
algorithm in §2 — so a ticket is never left with no attempt made.

**Step 3 — Escalation, if the customer isn't satisfied.**
Every time the customer replies while the ticket is still AI-handled, their
message is scored for sentiment (angry/frustrated/neutral/satisfied) and
for an explicit request to speak to a human. Enough of that signal
(configurable, default: two strikes, or one direct request) escalates the
ticket: a human agent is auto-assigned exactly like the queue-owner
algorithm in §2, `handling_mode` flips to `'human'`, a customer-visible
handoff message is posted, and — best-effort — an AI-written internal
summary is added so the agent isn't starting cold. A staff member replying
at any point, or an admin manually reassigning the ticket, also ends
AI-handling immediately, even below that threshold.

**Step 4 — The ticket lands on a human's queue.**
Once assigned, agents see it in `GET /tickets`, but **only if it was
assigned to them** — an agent's ticket list is their personal queue, not
the whole system. Admins see everything by default. Customers only ever
see their own tickets. All three rules are enforced server-side, not just
hidden in the UI. Admins additionally get a live "Live Conversations"
dashboard (`AdminMonitor.jsx`) that updates in real time as tickets and
messages come in, without ever polling — and a site-wide toast the instant
any ticket's SLA clock actually breaches, wherever in the app they are.

**Step 5 — An agent works it.**
Through `TicketDetail.jsx`'s "Manage ticket" panel (staff-only), the agent
can change status, category, or priority — each change is its own `PATCH
/tickets/{id}` call, each one pushed live to anyone else watching that
ticket, and each category/priority change that disagrees with the ML
suggestion is logged as feedback (§7). Reassigning to a *different* agent
is admin-only. The agent can reply, leave an **internal note** (staff-only,
stripped from the API response before it ever reaches a customer's browser
or a customer's WebSocket — enforced at the data layer, not by hiding a UI
element), insert a saved or AI-suggested **canned response** instead of
retyping something common, and attach files to either the ticket or a
specific reply.

The *first* non-internal reply from any agent stamps the SLA "first
response" time — unless the AI's own reply during triage already claimed
that slot, which it usually will for AI-first tickets.

**Step 6 — Resolution.**
When status is set to `resolved` for the first time — by an agent, or by
the AI during triage — the resolution timestamp is stamped and compared
against the resolution deadline — once and permanently, not recomputed
later. At the same moment, the ticket's text is embedded and stored so it
can show up in future "similar tickets" searches (best-effort — if that
call to Gemini fails, the ticket still resolves normally, it just isn't
searchable yet).

**Step 7 — Customer rates it.**
Once a ticket is `resolved` or `closed`, the customer can leave a 1–5 star
rating with an optional comment. They can come back and edit it later; the
same endpoint handles both the first submission and any edit.

**Step 8 — GenAI assist and similar tickets (available throughout once human-handled, staff only).**
At any point while a ticket is open, the agent can ask Gemini (or Groq) to
summarize the thread, draft a reply, or write resolution notes — all three
build from the same non-internal transcript, and can factor in attached
screenshots. The result is shown for review; a drafted reply can be copied
into the reply box with one click, but it is never auto-posted. Separately,
a "similar past tickets" panel and "suggested canned responses" chips run
quietly in the background, surfacing what looks like this ticket based on
meaning, not keywords — useful for reusing a known fix.

**Throughout, for admins: an analytics dashboard** (`AdminAnalytics.jsx`,
§7) rolls up ticket volume, category mix, sentiment, SLA compliance, and
CSAT from data the app is already tracking, and an **ML feedback page**
(`AdminMlFeedback.jsx`, §7) shows how many corrections have accumulated and
lets an admin trigger a retrain with one click.

## 6. Code organization

### Backend (`backend/app/`)

| File | Responsibility |
|---|---|
| [main.py](backend/app/main.py) | Creates the FastAPI app, wires CORS (only `localhost:5173` allowed), registers all nine routers, wires the WebSocket manager to the event loop at startup, runs an in-process background task that sweeps for newly-breached SLA clocks every 60 seconds, exposes `/health`. |
| [config.py](backend/app/config.py) | Reads settings (DB URL, JWT secret, Gemini keys/models, optional Groq keys/model, AI-escalation threshold, upload limits, password-reset TTL) from `.env`. One object, imported everywhere `settings` is needed. |
| [database.py](backend/app/database.py) | SQLAlchemy engine + session factory, `get_db()`, and startup bootstrapping: enables the `pgvector` Postgres extension, then runs `ensure_schema_migrations()` — a fixed list of additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements that backfill newer columns onto an already-running database, since there's no migration framework. |
| [models.py](backend/app/models.py) | Every database table as a Python class: `User`, `Category`, `Priority`, `Ticket`, `Comment`, `SLAPolicy`, `SLAHistory`, `TicketRating`, `CannedResponse`, `MLFeedback`, `Attachment`, `PasswordResetToken`. This *is* the schema — no separate migration files. |
| [schemas.py](backend/app/schemas.py) | Pydantic models — the API's public "contract." Every request body and response shape is defined here, separate from the DB models. |
| [auth.py](backend/app/auth.py) | Password hashing (bcrypt) and JWT create/decode. Pure functions, no DB access. |
| [deps.py](backend/app/deps.py) | Reusable FastAPI dependencies: `get_current_user` (decode JWT → load user from DB → reject if deactivated), `require_staff`, `require_admin`. |
| [seed.py](backend/app/seed.py) | One-time script: inserts reference data (categories, priorities, SLA policies) and 5 demo staff logins (1 admin, 4 agents — customers self-register). |
| [ws_manager.py](backend/app/ws_manager.py) | The in-memory "who's connected and watching what" registry that powers live updates — see §7. |
| [backfill_embeddings.py](backend/app/backfill_embeddings.py) | A one-off script to generate embeddings for resolved tickets that predate the similar-tickets feature. |
| [routers/auth.py](backend/app/routers/auth.py) | Register, login, `/me`, availability toggle, the forgot-password / reset-password pair, and `/auth/demo-accounts` (powers the Login page's one-tap demo logins). |
| [routers/reference.py](backend/app/routers/reference.py) | Read-only lookup endpoints: `/categories`, `/priorities`, `/agents` (the last one includes each agent's current ticket load). |
| [routers/users.py](backend/app/routers/users.py) | Admin-only staff account management — create agent/admin accounts, list users, change role or active status. |
| [routers/tickets.py](backend/app/routers/tickets.py) | The biggest file by far — ticket CRUD, comments, ratings, similar-tickets, the AI reassign trigger, the `/classify` preview endpoint, and the three GenAI action endpoints. Also owns the shared visibility rules and triggers AI-first triage / ML-feedback logging. |
| [routers/canned_responses.py](backend/app/routers/canned_responses.py) | CRUD for reusable reply templates, plus `/canned-responses/suggest` (semantic ranking against a ticket). |
| [routers/attachments.py](backend/app/routers/attachments.py) | Upload, download, and delete files on a ticket or a specific reply. |
| [routers/ws.py](backend/app/routers/ws.py) | The two WebSocket endpoints — one per ticket, one for admins watching everything. |
| [routers/ml_admin.py](backend/app/routers/ml_admin.py) | Admin-only: ML correction stats, and a "retrain now" endpoint that closes the active-learning loop in-request — see §7. |
| [routers/analytics.py](backend/app/routers/analytics.py) | Admin-only: one aggregate endpoint powering the Analytics dashboard — see §7. |
| [services/sla.py](backend/app/services/sla.py) | The SLA state machine, plus the proactive breach-scan used by `main.py`'s background sweep — see §7. |
| [services/ml_service.py](backend/app/services/ml_service.py) | Loads the two trained model files once per process, exposes `predict()`, and `reload_models()` to hot-swap in a freshly retrained pair. |
| [services/ml_feedback_service.py](backend/app/services/ml_feedback_service.py) | Logs human corrections of ML suggestions and reshapes them into training rows for a retrain — see §7. |
| [services/genai_service.py](backend/app/services/genai_service.py) | Builds the ticket transcript (+ attached screenshots), routes text generation to Gemini or Groq depending on config, and translates any failure into a clean error instead of a crash. |
| [services/rag_service.py](backend/app/services/rag_service.py) | Builds/stores ticket *and* canned-response embeddings and runs the similarity search — see §7. |
| [services/ai_triage_service.py](backend/app/services/ai_triage_service.py) | The AI-first triage chatbot: replies to new tickets, scores customer sentiment, and escalates to a human past a configurable threshold — see §7. |
| [services/assignment_service.py](backend/app/services/assignment_service.py) | Picks the best agent for a ticket (at creation fallback, or on AI escalation, or on demand) — see §7. |
| [services/password_reset_service.py](backend/app/services/password_reset_service.py) | Issues and validates single-use, time-limited reset tokens. |
| [services/ticket_access.py](backend/app/services/ticket_access.py) | The one shared "can this user see this ticket?" rule, reused by the REST routes, the WebSocket routes, and the attachment routes, so it's defined once and can't drift between them. |

### ML training (`backend/ml/`) — run offline, not part of the live API

| File | Responsibility |
|---|---|
| [generate_dataset.py](backend/ml/generate_dataset.py) | Builds a synthetic "historical tickets" CSV from templates — realistic subject/description text per category, with priority assigned by a weighted random draw *plus* an urgency phrase appended to the text. That phrase is what gives the priority model real signal to learn from, independent of category. |
| [train.py](backend/ml/train.py) | Loads a CSV, trains two independent `TF-IDF → Logistic Regression` pipelines (one for category, one for priority), evaluates each on a held-out 20% test split, and saves both as `.joblib` files. Exposed as a callable `train_all()` too, so the admin-triggered retrain endpoint doesn't need to shell out to a subprocess — see §7 for what it's doing line by line. |
| [build_dataset_with_feedback.py](backend/ml/build_dataset_with_feedback.py) | Appends every logged `MLFeedback` correction on top of the synthetic dataset and writes an augmented CSV — the input to a retrain that actually learns from real agent corrections, not just synthetic data. See §7. |

### Frontend (`frontend/src/`)

| File | Responsibility |
|---|---|
| [main.jsx](frontend/src/main.jsx) | Entry point — mounts the app inside a router and the auth context. |
| [App.jsx](frontend/src/App.jsx) | Branches on whether a user is logged in and renders one of two route tables — public auth pages, or the full app shell with ticket/admin pages (now including `/admin/analytics` and `/admin/ml-feedback`). |
| [api/client.js](frontend/src/api/client.js) | One shared `axios` instance. An interceptor automatically attaches the JWT from `localStorage` to every outgoing request. |
| [hooks/useWebSocket.js](frontend/src/hooks/useWebSocket.js) | A generic reconnecting-WebSocket hook (auto-retries on a 2s backoff) used across several pages and `AppShell` to receive live pushes. |
| [context/AuthContext.jsx](frontend/src/context/AuthContext.jsx) | Holds the logged-in user in React state, rehydrates from `/auth/me` on load, and exposes an `setAvailability()` helper for the agent status toggle. |
| [utils/sla.js](frontend/src/utils/sla.js) | Pure presentation helpers — ring percentage, remaining/overdue time, plain-language headline — derived from the backend's pre-computed breach flags. Never re-decides breach state itself. |
| [utils/files.js](frontend/src/utils/files.js), [utils/avatar.js](frontend/src/utils/avatar.js) | Small formatting helpers: the attachment file-picker's `accept` string + per-type icon + size formatting; deterministic initials + color-class for `Avatar.jsx`. |
| [pages/Login.jsx](frontend/src/pages/Login.jsx), [Register.jsx](frontend/src/pages/Register.jsx) | Simple forms wired to `AuthContext.login()` / `.register()`. Registration always creates a customer account. Login also fetches `GET /auth/demo-accounts` for a one-tap demo-login list. |
| [pages/ForgotPassword.jsx](frontend/src/pages/ForgotPassword.jsx), [ResetPassword.jsx](frontend/src/pages/ResetPassword.jsx) | Request a reset link, then consume the token from the URL to set a new password. |
| [pages/TicketList.jsx](frontend/src/pages/TicketList.jsx) | The ticket queue/table with filters, including a `?sla=breach` quick filter — live-updated for admins over WebSocket. |
| [pages/NewTicket.jsx](frontend/src/pages/NewTicket.jsx) | The ticket creation form: AI category/priority preview, optional file attachments. |
| [pages/TicketDetail.jsx](frontend/src/pages/TicketDetail.jsx) | By far the busiest page: comment thread with attachments and sentiment tags, the SLA panel, the staff-only "Manage ticket" panel, ratings, similar tickets, the GenAI assistant panel, and the canned-responses manager with semantic suggestion chips. Live-updated over WebSocket. |
| [pages/AdminUsers.jsx](frontend/src/pages/AdminUsers.jsx) | Admin-only: create/deactivate staff accounts. |
| [pages/AdminMonitor.jsx](frontend/src/pages/AdminMonitor.jsx) | Admin-only: a live, WebSocket-driven dashboard of every active ticket system-wide. |
| [pages/AdminAnalytics.jsx](frontend/src/pages/AdminAnalytics.jsx) | Admin-only: hand-rolled inline-SVG charts for ticket volume, category mix, sentiment, SLA compliance, and CSAT, from one aggregate endpoint. |
| [pages/AdminMlFeedback.jsx](frontend/src/pages/AdminMlFeedback.jsx) | Admin-only: correction-count stats and a "Retrain models now" button that shows the resulting per-class metrics. |
| [components/AppShell.jsx](frontend/src/components/AppShell.jsx) | Layout wrapper for every logged-in page: renders `Sidebar` + a breadcrumb bar, and independently keeps one admin WebSocket connection alive just to catch `sla.breached` events and pop a toast from anywhere in the app. |
| [components/Sidebar.jsx](frontend/src/components/Sidebar.jsx) | Left rail — role-aware links (including an "SLA Breaches" alert link with a live count), the agent availability toggle, logout. |
| [components/Badges.jsx](frontend/src/components/Badges.jsx) | `StatusBadge` / `PriorityBar` / `SLABadge` — pure display components. |
| [components/FilePicker.jsx](frontend/src/components/FilePicker.jsx), [AttachmentList.jsx](frontend/src/components/AttachmentList.jsx) | Pick files to upload; render/download/delete existing attachments. |
| [components/LiveDot.jsx](frontend/src/components/LiveDot.jsx) | The small connected/disconnected indicator fed by `useWebSocket`'s status. |

**Pattern worth calling out:** every page fetches its own data with plain
`useState`/`useEffect` — there's no global cache library. After a REST
mutation (a `PATCH`, a new comment), the page re-fetches rather than
patching local state optimistically. Where it matters most (an open
ticket, the admin dashboards), that's topped up with live WebSocket events
so other people's changes still show up without a manual refresh.

## 7. The things worth explaining carefully

### AI-first triage, explained simply

The core idea: a new ticket shouldn't have to wait for a human if the AI can
actually help, and the system should notice — not guess — when it can't.

`ai_triage_service.py`, driven from two places: right after a ticket is
created (`handle_new_ticket()`), and on every customer reply while the
ticket is still AI-handled (`handle_customer_message()`).

1. There's a real `users` row for "AI Assistant" (created lazily, the first
   time it's needed), so every AI-authored message looks like a normal
   comment in the thread, attributed consistently, rather than a special
   system message. It can't log in and never appears in the agent-picker
   dropdown.
2. On ticket creation, the AI always gets one unconditional attempt — it
   replies with an actual attempt to help, informed by the ticket text and
   similar past resolved tickets, and that reply counts as the ticket's
   official "first response" for SLA purposes. If it believes the issue is
   now solved, it resolves the ticket itself.
3. On every later customer message (while still AI-handled), the AI's
   response comes back as structured data, not just prose: a sentiment
   read on the customer's message, whether they explicitly asked for a
   human, whether it thinks the issue is now resolved, and the reply text
   itself. A running "dissatisfaction count" increments on negative
   sentiment or an explicit request for a human.
4. Once that count crosses a threshold (2 strikes by default, configurable,
   and one direct request for a human is enough on its own), the system
   escalates: it auto-assigns a real agent using the same "best available"
   algorithm as any other assignment, posts a customer-visible handoff
   message, and — best-effort — writes an internal AI-generated summary of
   the conversation so far so the agent doesn't start cold.
5. A human jumping in at any point (an agent replying, or an admin manually
   reassigning) always takes the ticket out of AI-handling immediately,
   even if the dissatisfaction count never crossed the threshold.
6. If the AI call itself fails — Gemini/Groq down or unconfigured — the
   system fails safe rather than silently: at creation time, it falls back
   to immediately assigning a human (the pre-AI-triage behavior); on a
   later customer message, the message is still saved, it just sits
   without a reply until the AI (or a human) can respond.

### ML feedback & active learning, explained simply

The ML classifier is trained once, offline, on synthetic data — left alone,
it would never get better at reflecting how this specific team actually
categorizes and prioritizes tickets. So every time a human's final answer
disagrees with what the model suggested, that disagreement is captured as a
labeled training example instead of being thrown away.

1. Whenever an official category/priority ends up different from the ML
   suggestion — whether the customer overrode the category at ticket
   creation, or a staff member changed category/priority afterward — one
   row is logged: which field, what the model guessed, what the human
   actually set, and a copy of the ticket's text (so the example survives
   even if that ticket is later edited or deleted).
2. An admin can see a running tally of how many corrections have piled up,
   broken down by field and by which value corrections tend to land on
   (useful for spotting "the model keeps guessing X when it should say Y").
3. Clicking "Retrain models now" combines the original synthetic dataset
   with every real correction collected so far, retrains both classifiers
   fresh, and immediately swaps the newly trained models into the live
   process — the very next ticket classified uses the improved model, with
   **no server restart**. The resulting precision/recall/F1 numbers are
   shown right in the admin page, the same numbers that would otherwise
   only appear in a terminal running the training script by hand.

This turns "the model is wrong sometimes" from a permanent, static fact
into a feedback loop an admin can close from the browser.

### The ML pipeline, explained simply

Training happens **offline**, by running two scripts by hand — it is not
something that happens live while the API is running:

1. `generate_dataset.py` creates a CSV of ~1,100 fake-but-realistic tickets
   (220 per category × 5 categories), each with a category label and a
   priority label baked into the text itself.
2. `train.py` turns each ticket's `subject + description` into numeric
   features (`TF-IDF` — essentially "which words/word-pairs are unusually
   frequent in this text") and fits a `Logistic Regression` classifier on
   top. It does this **twice**, independently — one model only ever learns
   to predict category, a separate model only ever learns to predict
   priority. Each is tested against ticket text it never saw during
   training, and a precision/recall report prints to the console.
3. The two trained models are saved to disk as `.joblib` files.

At runtime, `ml_service.py` loads those two files into memory **once** and
reuses them for every request after that — no retraining, no network call,
just fast in-process math. If those files don't exist yet, the system
fails gracefully — a clear "not trained yet" error instead of a crash, and
ticket creation simply skips auto-classification.

**Retraining** means re-running both scripts by hand; the API picks up the
new files the next time it's restarted.

### The SLA engine, explained simply

Every priority level has a promised response time and resolution time
(e.g., "critical" = respond within 1 hour, resolve within 8). The engine has
two different strategies depending on whether something has already
happened:

- **Once an event happens** (the first staff reply, or the ticket being
  marked resolved), that moment is a historical fact — it's written to the
  database permanently, along with whether it was on-time or late *at that
  exact moment*.
- **Before that event happens**, "is this late?" isn't a fact yet — it
  depends on what time it is *right now*. So the *display* value is just
  recomputed live, every single time someone views the ticket, rather than
  relying on a background job to keep it current. That's why an ignored,
  overdue ticket immediately shows "breached" the moment anyone looks at
  it. On screen, this shows up as a progress ring plus a plain colored
  headline — 🟢 on track, ⚠️ at risk, 🔴 overdue — so it reads at a glance
  without needing to understand the underlying deadlines.
- **There is, separately, a background job** — but it exists for
  *notification*, not for the display value above. Every 60 seconds, the
  system scans for SLA clocks that have crossed their deadline since the
  last scan and haven't been announced yet, marks them so they're never
  re-announced, and pushes a live alert to every admin — a toast that pops
  up no matter what page they're on, not just the ticket in question. This
  is the one thing in the app that pushes a live update without a human
  action triggering it.

### AI ticket assignment, explained simply

The goal is: a new ticket should land with someone who can actually pick it
up soon, not just round-robin blindly. The algorithm (`assignment_service.py`):

1. Only considers active **agents** (not admins — an admin can still be
   assigned manually, just not by this automatic algorithm).
2. Strongly prefers availability: it looks for any **online** agent first;
   only if there are none does it consider **busy** agents; only if there's
   truly nobody online or busy does it fall back to anyone else. Current
   workload never overrides this preference — an online agent with 5
   tickets is still picked over a busy agent with 1.
3. Within whichever group it lands on, it picks whoever currently has the
   fewest open/in-progress tickets.
4. If there are no agents at all yet, the ticket is explicitly marked
   "unassigned" with a note explaining why, rather than silently having no
   owner and no explanation.

This runs automatically the moment a human actually needs to be assigned —
either as a fallback if AI-first triage couldn't run at all (GenAI down),
or the moment the AI escalates a ticket (§7 above) — and an admin can also
re-run it on demand (e.g. after reassigning agents' availability) via an
"✨ Auto-assign" button. A separate, always-available path lets an admin
override this and assign any ticket to any agent (or even another admin)
by hand — the ticket then shows "👤 Manual" instead of "✨ AI assigned" or
"🚨 Escalated by AI" so it's always clear which one happened.

### Similar tickets & canned-response suggestions, explained simply (retrieval-augmented search)

The idea: once a ticket is resolved, its text (and the public conversation
that resolved it) becomes a mini case study. The next time a similar
problem comes in, the system should be able to say "here's how we solved
this before." The same mechanism is reused to rank an agent's saved
canned-response templates by relevance, instead of making them scroll an
alphabetical list or guess the right keyword.

1. **When a ticket resolves**, its subject, description, and every
   non-internal reply are turned into one block of text, sent to Gemini's
   embedding model, and converted into a list of 768 numbers — a
   mathematical "fingerprint" of what the ticket was about. That fingerprint
   is stored on the ticket (via Postgres's `pgvector` extension, which
   understands how to compare these fingerprints efficiently).
2. **While working any ticket**, the system quietly fingerprints *that*
   ticket too and asks Postgres: "of all resolved tickets, which
   fingerprints are closest to this one?" The closest matches — measured by
   meaning, not shared keywords — come back as "similar tickets," each with
   a similarity score.
3. There's a small privacy rule layered on top: an agent can see the
   subject/snippet of a similar ticket even if it isn't theirs (useful
   context), but can't click through to open it unless they're actually
   allowed to (assigned to them, or they're an admin) — so this feature
   can't be used to peek into a colleague's ticket.
4. If Gemini is unreachable when a ticket resolves, that one ticket just
   silently doesn't get a fingerprint (the resolution itself still
   succeeds) — a background backfill script exists to catch these up later.
5. Canned-response templates get the same fingerprint treatment on save, so
   `GET /canned-responses/suggest?ticket_id=...` can rank them against the
   ticket currently being worked the exact same way. If nothing's embedded
   yet (no Gemini key, or nothing saved since), it falls back to a plain
   alphabetical list rather than erroring.

### Real-time updates, explained simply

Instead of every page polling "anything new?" every few seconds, the
backend pushes changes out the instant they happen, over a WebSocket (a
persistent two-way connection, though in this app only the server actually
sends anything after the initial handshake).

- Opening a ticket's page joins that ticket's "room." Any status change,
  new reply, or reassignment on that ticket gets pushed to everyone
  currently looking at it.
- Admins additionally have an "everything" room, which is what powers the
  live ticket list, the "Live Conversations" dashboard, and — mounted once
  for the whole app rather than any single page — a site-wide listener
  that pops a toast the instant any ticket's SLA clock actually breaches
  (pushed by the background sweep described above, not by a REST call).
  New tickets appear, messages update, agent availability dots change
  color, and breach alerts surface, all without a page refresh.
- The same staff-only filtering that applies to internal notes over the
  REST API applies here too — an internal note pushed live still never
  reaches a customer's browser.
- This is a lightweight, in-memory implementation — fine for one running
  copy of the backend, but it wouldn't by itself scale to multiple backend
  processes/servers without extra work (see §8).

### Authorization model, explained simply

There are three roles: `customer`, `agent`, `admin`. Every protected
endpoint checks the caller's role via one of three reusable rules defined
once in [deps.py](backend/app/deps.py): "any logged-in (and still active)
user," `require_staff` ("must be agent or admin"), and `require_admin`
("must be admin"). `require_admin` is now actively used — it gates staff
account management and manual ticket reassignment, so admin is a
meaningfully different role from agent today, not just a label.

On top of the role check, there's a row-level rule that isn't just "what
role are you": a customer can only see *their own* tickets, and — this is
the one that changed since earlier versions of this project — **an agent
can only see tickets assigned to them**, not every ticket in the system.
Only an admin can see everything. This is enforced by filtering the
database query itself (for lists) and by a shared check function (for a
single ticket, reused identically by the REST routes, the WebSocket
routes, and the attachment routes) — never by the frontend hiding a
button. The frontend also hides staff-only UI for customers and admin-only
UI for agents, but that's just convenience; the real gatekeeping happens
on the server.

**Deactivation** is enforced the same way: an admin can flip a staff
account to inactive, and that takes effect immediately — even a still-valid
JWT the user is holding gets rejected on their very next request, not just
on their next login attempt.

## 8. What this is *not* (POC shortcuts, worth naming up front)

Good to mention proactively so it reads as "I know the gaps," not as gaps
your manager finds themselves:

- No automated tests.
- No database migration tool (Alembic) — tables are just created from the
  current model definitions.
- No rate limiting anywhere (including on the forgot-password endpoint).
- No refresh-token flow — an expired JWT just means logging in again.
- Password reset exists, but "sending the email" is a `print()` to the
  server console — there's no real email/SMS provider wired in.
- The ML training data is synthetic (template-generated), not real
  historical tickets.
- File attachments live on local disk, not cloud storage — doesn't scale
  past one machine, and a failed multi-file upload can leave a stray file
  on disk that nothing references.
- The WebSocket connection registry is in-memory and single-process —
  broadcasts wouldn't reach clients connected to a different backend
  process if this were ever run with multiple workers/instances.
- If Gemini is briefly unreachable at the exact moment a ticket resolves,
  that ticket quietly ends up without a "similar tickets" fingerprint —
  there's a manual backfill script, but nothing retries automatically.
- SLA-breach alerting is in-app only (a WebSocket toast to whichever admins
  currently have a browser tab open) — there's no email/SMS/Slack paging,
  so a breach that happens while the whole team is logged out goes
  unnoticed until someone opens the app.
- The admin-triggered model retrain runs synchronously, in the same
  request/process serving live traffic — fine at this dataset's small
  scale, but a real-sized training set would need to move to a background
  job instead of blocking an API worker for the duration of training.
- The analytics dashboard recomputes every metric from scratch on every
  request, with no caching or pre-aggregation — fine here, but wouldn't
  scale to a very large ticket history without added latency.

## 9. Anticipated questions and short answers

- **"What happens if the AI (Gemini) is down or misconfigured?"** Text
  generation (summarize/draft/notes) fails cleanly with an error shown in
  the UI. Embedding a resolved ticket for similarity search fails silently
  in the background — the ticket still resolves normally, it just isn't
  searchable until backfilled. Either way, the rest of the app (tickets,
  SLA, ML classification, assignment) is completely unaffected.
- **"Does the AI ever act without a human?"** Yes, deliberately, during
  AI-first triage: the AI Assistant replies directly to the customer, and
  can resolve the ticket itself, with no human reviewing that message
  first — that's the entire point of the feature. AI ticket *assignment*
  also acts automatically, and an admin can always see whether a given
  assignment was "✨ AI assigned," "🚨 Escalated by AI," or "👤 Manual" and
  override it. The one place the AI is never allowed to act unsupervised
  is **once a ticket is human-handled**: summaries, draft replies, and
  resolution notes are always shown to the agent for review/editing before
  anything is posted — the AI never posts on a human-owned ticket.
- **"What if the ML model hasn't been trained?"** Ticket creation still
  works — it just skips auto-classification, and the "Suggest" button
  returns a clear error instead of failing silently.
- **"Can a customer see another customer's ticket, or an internal note?"**
  No, both are blocked at the database-query/serialization level in the
  backend — over REST and over WebSocket alike — independent of anything
  the frontend does.
- **"Can an agent see every ticket, or just their own?"** Just their own —
  an agent's ticket list and any direct link to someone else's ticket are
  both blocked server-side. Only admins have system-wide visibility.
- **"What happens if a customer or agent loses their internet connection
  mid-session?"** The WebSocket hook auto-reconnects every 2 seconds; once
  it's back, ordinary page reloads/refetches catch up on anything missed
  in between (there's no "replay missed events" mechanism — a live update
  you weren't connected for just doesn't arrive, but the underlying data
  is always there on next load).
- **"How would this scale to real usage?"** The main gaps are in §8 —
  tests, migrations, real training data, a real email provider, cloud file
  storage, and a shared (not in-memory) WebSocket backend would be the
  first investments before this went past demo stage.
