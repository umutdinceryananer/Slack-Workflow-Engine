# Slack Workflow Engine

Central, configuration-driven Slack workflow bot. A single Slack app handles multiple request/approval flows (e.g., refund, expense, PTO) via JSON config. This repository is structured as a learning/portfolio project and evolves across three phases (MVP → Features → Production-grade DevOps).

**Highlights (MVP)**
- Slash command `/request refund` opens a modal based on config
- Stores requests in a database; posts a channel message with Approve/Reject
- Updates status on button clicks with basic authorisation
- Structured JSON logging with end-to-end trace IDs; `/healthz` endpoint

**Phase-2 Foundations (in progress)**
- App Home publishes on `app_home_opened`, debouncing per user and surfacing recent requests alongside pending approvals

**Tech Stack**
- Python 3.11+, Slack Bolt for Python, Flask, SQLAlchemy, Pydantic, structlog
- SQLite for local development (Postgres later), Docker/CI optional in early phases

**Repository Notes**
- Planning/issue docs live under `Development_Documents/` and are not part of the shipped app.
- Issue lists: `Issue_List/Issue_List_1.md`, `Issue_List/Issue_List_2.md`, `Issue_List/Issue_List_3.md`, and `Issue_List/Issue_List_Optional.md`.

## Local Setup (Step by Step)

1. **Prerequisites**
   - Python 3.11+
   - A Slack workspace where you can create and install custom apps
   - [ngrok](https://ngrok.com/download) (free tier is enough)

2. **Install dependencies**
   ```powershell
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   ```bash
   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create the Slack app**
   - Go to `https://api.slack.com/apps` → “Create New App (from scratch)”.
   - Add bot scopes under **OAuth & Permissions**: `commands`, `chat:write`, `views:open`, `views:write` (optionally `chat:write.public`).
   - Configure the slash command `/request` and Interactivity URL (both will point to your ngrok URL + `/slack/events`).
   - Install/Reinstall the app to your workspace to obtain a Bot User OAuth token.
   - Copy the **Signing Secret** from **Basic Information**.
   - Invite the bot user to the channel referenced in your workflow config.

4. **Populate environment variables**
   - Copy `.env.example` to `.env` and fill in:
     - `SLACK_BOT_TOKEN` (xoxb-…)
     - `SLACK_SIGNING_SECRET`
     - `APPROVER_USER_IDS` (comma-separated Slack user IDs, e.g. `U123,U456`)
     - `DATABASE_URL` (`sqlite:///local.db` is fine for local runs)
      - Optional: `HOME_RECENT_LIMIT` / `HOME_PENDING_LIMIT` to control how many items the App Home sections display (defaults to `10`)
   - Before running the app in a PowerShell session, load the variables:
     ```powershell
     Get-Content .env | ForEach-Object {
         if ($_ -match '^\s*#' -or $_ -eq '') { return }
         $name, $value = $_ -split '=', 2
         [System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
     }
     ```

5. **Prepare the database schema (first run only)**
   ```powershell
   python -c "from slack_workflow_engine.db import Base, get_engine; Base.metadata.create_all(get_engine())"
   ```
   Subsequent runs reuse the same SQLite file.

6. **Expose the local server to Slack**
   ```powershell
   ngrok http 3000
   ```
   Update the slash command and interactivity URLs with the HTTPS endpoint that ngrok prints (e.g. `https://abcd1234.ngrok-free.dev/slack/events`).

7. **Run the application**
   ```powershell
   python app.py
   ```
   The app binds to port `3000`; ngrok forwards Slack traffic to `/slack/events`.

8. **Manual E2E smoke test**
   - In Slack, run `/request refund`, fill the modal, and submit.
   - A channel message appears with Approve/Reject buttons; only `APPROVER_USER_IDS` can confirm.
   - Approving or rejecting updates the database and edits the Slack message. Unauthorized users receive an ephemeral warning.
   - Open the bot’s App Home (Slack → Messages → App → Home) to review “My Requests” and “Pending Approvals”. Entries appear after you submit/approve, and rapid refreshes are debounced for rate-limit safety.

9. **Run automated tests**
   ```bash
   pytest -q
   ```

### Structured logging & trace IDs
- Logs are emitted as JSON via structlog; each slash command, modal submission, button action, and webhook handler binds a unique `trace_id`.
- Background tasks inherit the same structlog context, so `request_created`, `approved`, `rejected`, `unauthorized_attempt`, and `webhook_failed` events can be stitched together with the originating request.
- Sensitive payload bodies are never logged; only correlation metadata and high-level status fields are captured.
- Automated coverage (`tests/test_background.py`, `tests/test_submission.py`, `tests/test_approve_action.py`, `tests/test_reject_action.py`) asserts that `trace_id` survives async boundaries and that no payload data leaks into structured logs.
- Slack API failures are reported as `webhook_failed` with the channel, status code, and Slack error string so you can troubleshoot without exposing payload data. Tail with `pytest -k background --log-cli-level=INFO` to validate behaviour locally.

### Resetting your local database
- If you want to start from a clean slate, load your `.env` values and run:
  ```bash
  python scripts/reset_local_db.py
  ```
  This drops and recreates the schema defined in `slack_workflow_engine.models`.

# Health Endpoint
- `GET /healthz` returns overall application health including:
  - `config`: current configuration validity
  - `db`: database connectivity
  - `version`: app version from the `VERSION` file
- Failing checks return HTTP `503` with diagnostic details in the JSON payload.

## FAQ / Troubleshooting

**Modal doesn’t open after `/request refund`**
- Ensure the slash command form was saved with the correct ngrok URL.
- Reinstall the Slack app after changing scopes or command settings.
- Confirm the bot is invited to the channel (Slack returns `not_in_channel` otherwise).

**Channel message fails with `invalid_auth` or `channel_not_found`**
- Check that `SLACK_BOT_TOKEN` matches the workspace where you’re testing.
- Update `workflows/refund.json` → `notify_channel` with the actual channel ID (Channel details → “Copy channel ID”).
- Invite the bot user to that channel before testing.

**Duplicate submission raises `UNIQUE constraint failed: requests.request_key`**
- The app deduplicates identical submissions (same user, workflow type, payload). Use a different payload for testing or clear the local DB (`sqlite3 local.db "delete from requests;"`) before re-running.

**Approvers click Approve/Reject twice and nothing happens**
- The first click decides the request; subsequent clicks return an ephemeral notice (“This request has already been decided.”). The channel message is not updated again.

**Slash command returns nothing**
- Modal handlers run asynchronously; if you still see nothing, verify that ngrok is running and the Request URL uses `https://…/slack/events`.
- Check the Flask console for `Failed to open workflow modal` logs – they include Slack’s error code.

**CI/CD**
- A basic GitHub Actions workflow (tests) is introduced early; advanced pipeline and security scans arrive in Phase-3.

**Roadmap**
- Phase-1: MVP bot + config + DB + actions + health/logs
- Phase-2: Home Tab, multi-level approvals, webhooks, RBAC, metrics
- Phase-3: Docker/K8s/Helm, GitOps/CI, observability, security, HA/DR
