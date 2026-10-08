# Customer Support Ticket System — Project Overview

*A plain-language summary of what this application does and how it works.*

## What it is

A web application where customers can raise support tickets and support
agents can track, respond to, and resolve them — with AI built in to help
agents work faster, automatic ticket routing, and live updates so nothing
sits unnoticed.

Think of it as a lightweight version of tools like Zendesk or Freshdesk,
built as a hands-on learning project.

## Who uses it

The app has three types of users, and everyone sees a version of the app
suited to their role:

| Role | What they can do |
|---|---|
| **Customer** | Raise a ticket, chat with the AI assistant (and get handed off to a human if needed), track status, reply, attach files, and rate the resolution |
| **Agent** | Work their own assigned tickets (including ones escalated to them by the AI), reply, use AI tools, set their availability |
| **Admin** | Everything an agent can do, plus manage staff accounts, manually reassign any ticket, watch a live dashboard of every active conversation, view the analytics dashboard, and trigger a model retrain |

## Core features

**1. AI-first triage — an AI agent handles every new ticket first**
When a ticket comes in, it doesn't wait in a queue for a human — an AI
assistant reads it immediately and starts a real conversation with the
customer, trying to solve the issue itself using the ticket's own content
plus how similar problems were solved before. If it judges the issue
resolved, it closes the ticket on its own. If the customer seems
frustrated or explicitly asks for a person, the system automatically hands
the conversation off to whichever available agent is best positioned to
take it, with an AI-written summary so the agent isn't starting cold.

**2. Ticket creation & tracking**
Customers describe their issue and can attach files (screenshots, PDFs,
Word docs); the system tracks it through a simple lifecycle — Open → In
Progress → Resolved → Closed.

**3. AI-assisted categorization, with a self-improving model**
When a ticket comes in, a machine-learning model automatically suggests
what category it belongs to (e.g. billing, technical issue) and how urgent
it is (low/medium/high/critical). Agents can accept the suggestion or
override it — the AI's original guess is always kept on record for
transparency. Every time a human overrides the model, that correction is
logged, and an admin can trigger a one-click retrain that folds those
corrections back into the model — no data-science pipeline required.

**4. Automatic ticket assignment**
The moment a ticket needs a human (either at creation, if AI triage isn't
available, or when the AI escalates), it's automatically routed to an
available agent — preferring whoever is online and currently has the
lightest workload. Admins can see whether an assignment was made by the
AI or by a person, and can manually reassign any ticket at any time.

**5. SLA tracking, with proactive breach alerts**
Every ticket gets a countdown clock based on its priority — e.g. a
"critical" ticket must get a first response within 1 hour and be resolved
within 8 hours. The app shows, at a glance, whether a ticket is on track,
at risk, or overdue — both on the ticket itself and in the ticket list.
A background check also runs every minute and pushes a live notification
to admins the moment a ticket's clock actually runs out, so a breach
doesn't require someone to happen to be looking at that ticket to notice.

**6. Live, real-time updates**
New tickets, new replies, and status changes appear instantly for anyone
watching — no manual refreshing. Admins have a "Live Conversations"
dashboard showing every active ticket across the whole team, updating in
real time, plus breach alerts that pop up no matter which page they're on.

**7. GenAI assistant for agents**
With one click, an agent can ask AI to:
- **Summarize** a long ticket thread (including reading any attached screenshots)
- **Draft a reply** to the customer (which the agent reviews and edits before sending — nothing is sent automatically)
- **Write internal resolution notes** for the record

**8. Canned responses, ranked by relevance**
Agents can save frequently-used reply templates (e.g. "Refund policy
explanation") and drop them into a reply instead of retyping the same
answer every time. The system also proactively suggests the most relevant
templates for the ticket currently being worked, matched by meaning rather
than requiring the agent to know the right keyword.

**9. Similar-ticket suggestions**
When working a ticket, an agent can see similar tickets that were already
resolved in the past — matched by meaning, not just keywords — useful for
reusing a known fix instead of solving the same problem from scratch.

**10. Customer satisfaction ratings**
Once a ticket is resolved, the customer can leave a 1–5 star rating with
an optional comment, and can edit it afterward — basic feedback tracking on
service quality.

**11. Internal notes**
Agents can leave notes on a ticket that are only visible to staff, never
to the customer — useful for handoffs or context that shouldn't be
customer-facing.

**12. Analytics dashboard**
Admins get a single dashboard rolling up ticket volume over time, category
mix, AI-detected customer sentiment, SLA compliance rates, and average
customer-satisfaction rating — all computed live from data the app is
already tracking, no separate reporting tool needed.

**13. Staff & account management**
Admins can create agent/admin accounts, and deactivate a staff account
instantly if needed (it locks them out immediately, not just on their next
login). Agents can set their own status — online, busy, or offline — which
feeds directly into automatic ticket routing.

**14. Password recovery**
Users who forget their password can request a reset link. (In this
practice build, the link is logged to the server instead of actually
emailed — see "Current status" below.)

## How it works (high level)

- Customers and agents use the same web app, just with different screens
  and permissions depending on their role.
- All data (tickets, users, replies, SLA timers, ratings, model
  corrections) lives in one central database.
- Two AI capabilities are used:
  - A small in-house-trained model that instantly categorizes/prioritizes
    new tickets (fast, runs locally, no external cost) — and improves over
    time as agents' corrections get folded back into a retrain.
  - A large language model (Google's Gemini by default, or Groq as a
    swappable alternative) for the more open-ended tasks — chatting with
    the customer during AI-first triage, writing summaries and draft
    replies, and finding similar past tickets / canned responses by
    meaning.
- A live connection keeps open ticket views, the admin dashboard, and a
  site-wide SLA-breach alert in sync automatically, instead of everyone
  needing to refresh the page.

## Current status

This is a **practice / proof-of-concept project**, not a production
product. It demonstrates the full workflow end-to-end, including AI-first
triage, password recovery, file attachments, automatic routing, live
updates, and an analytics dashboard — but intentionally skips things a
real production system would still need, such as:

- Automated testing
- Real email delivery for password-reset links (currently just logged on
  the server, not actually sent)
- Email/SMS/Slack alerts when an SLA is breached — today the app pushes an
  in-app notification to any admin who has it open, but nobody is paged if
  the team is logged out
- Rate limiting and other production-grade hardening
- Cloud file storage for attachments (currently stored on the single
  server's local disk)

## Technology used (for reference)

- **Backend:** Python (FastAPI) + PostgreSQL database
- **Frontend:** React
- **AI:** an in-house trained classifier for category/priority (with an
  active-learning retrain loop), plus Gemini or Groq for AI-first triage
  chat, summaries, draft replies, and similarity search
- **Real-time:** WebSockets for live, no-refresh updates, including
  proactive SLA-breach alerts

---
*For a full technical deep-dive, see `README.md`. For a narrated
walkthrough of the code, see `CODE_EXPLAINED.md`.*
