# Slack Workflow Engine

Central, configuration-driven Slack workflow bot. A single Slack app handles multiple request/approval flows (e.g., refund, expense, PTO) via JSON config. This repository is structured as a learning/portfolio project and evolves across three phases (MVP → Features → Production-grade DevOps).

**Highlights (MVP)**
- Slash command `/request refund` opens a modal based on config
- Stores requests in a database; posts a channel message with Approve/Reject
- Updates status on button clicks with basic authorisation
- Structured JSON logging; `/healthz` endpoint

**Tech Stack**
- Python 3.11+, Slack Bolt for Python, Flask, SQLAlchemy, Pydantic, structlog
- SQLite for local development (Postgres later), Docker/CI optional in early phases

**Repository Notes**
- Planning/issue docs live under `Development_Documents/` and are not part of the shipped app.
- Issue lists: `Issue_List/Issue_List_1.md`, `Issue_List/Issue_List_2.md`, `Issue_List/Issue_List_3.md`, and `Issue_List/Issue_List_Optional.md`.

**Getting Started**
- Requirements: Python 3.11+
- Create a virtual environment and install dependencies:
  - Windows PowerShell: `python -m venv .venv; . .venv/Scripts/Activate.ps1; pip install -r requirements.txt`
  - macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`

**Environment Variables**
- `SLACK_BOT_TOKEN` (xoxb-...), `SLACK_SIGNING_SECRET`
- `APPROVER_USER_IDS` (comma-separated Slack user IDs)
- `DATABASE_URL` (e.g., `sqlite:///local.db` for MVP)

**Run Locally (after scaffolding)**
- `python app.py`
- For Slack callbacks, expose `/slack/events` via a tunnel (e.g., ngrok)

**Tests**
- `pytest -q`

**CI/CD**
- A basic GitHub Actions workflow (tests) is introduced early; advanced pipeline and security scans arrive in Phase-3.

**Roadmap**
- Phase-1: MVP bot + config + DB + actions + health/logs
- Phase-2: Home Tab, multi-level approvals, webhooks, RBAC, metrics
- Phase-3: Docker/K8s/Helm, GitOps/CI, observability, security, HA/DR
