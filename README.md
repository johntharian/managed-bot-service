# Alter Managed Bot Service

This repository contains the standalone Python service designed to provide "Managed Bots" for Alter users. It acts as an integration layer between the core Alter asynchronous telecom infrastructure and LLM providers like Anthropic Claude and Google Gemini, granting bots permission-gated execution of tools (like Gmail and Google Calendar).

## Architecture Overview

The Managed Bot Service communicates with the core Alter platform entirely asynchronously via HTTP webhooks. 

- **Language:** Python 3.12+ (FastAPI)
- **Database:** PostgreSQL (asyncpg + SQLAlchemy + Alembic)
- **Background Jobs:** Celery + Redis
- **LLM Support:** Anthropic Claude (`claude-3-5-sonnet`) & Google Gemini (`gemini-2.5-flash`)

### Data Flow
1. Alter main server registers a user via `POST /provision`.
2. This service generates a `bot_url` and a `secret_key` for HMAC validation.
3. Arriving Alter messages hit `POST /bot/{user_id}` and verify the `X-Hub-Signature-256`.
4. The **Context Assembler** merges three memory channels:
   - **Thread History:** Fetched directly from the Alter main server via a shared service token.
   - **Working Memory:** Recent turns kept in Redis `context:{user_id}:{thread_id}`.
   - **User Memory:** Long-term facts from the PostgreSQL `user_memory` table.
5. The **LLM Orchestrator** calls the user's preferred LLM to process the intent.
6. The **Permission Engine** evaluates requested tool calls:
   - `full_auto`: Execution proceeds.
   - `ask_first`: Intercepts and drops into a Pending Approval DB state, awaiting human intervention via the config dashboard.
   - `read_only`/`denied`: Blocks execution.
7. The **Responder** returns the final text payload or action result to the Alter network via `POST /messages`.

## Project Structure

```
managed-bot-service/
├── alembic/                # Database migration scripts
├── app/
│   ├── api/                # FastAPI routers (bot.py, config.py, provision.py)
│   ├── approvals/          # Celery tasks and Approval Manager
│   ├── bot/                # LLM Orchestrator, Gemini adapter, and Alter Responder
│   ├── connectors/         # External tool wrappers (Gmail, GCal)
│   ├── context/            # Memory managers (Working, Long Term, Thread Fetcher, Assembler)
│   ├── core/               # App configuration, Database engine, and Security (Crypto/HMAC)
│   ├── models/             # SQLAlchemy ORM definitions
│   ├── permissions/        # Permission evaluation engine
│   └── schemas/            # Pydantic validation models
├── main.py                 # FastAPI Application Factory
├── celery_app.py           # Celery Worker Configuration
├── docker-compose.yml      # Local DB & Redis definitions
└── requirements.txt        # Python dependencies
```

## Setup & Running Locally

Ensure you have Python 3.9+ and Docker installed.

### 1. Start Infrastructure
This will spin up a dedicated Postgres DB on port `5433` and Redis on port `6380` to prevent clashing with the Go server.
```bash
docker-compose up -d
```

### 2. Environment Configuration
Copy the `.env.example` to `.env` and fill out the necessary secrets.
```bash
cp .env.example .env
```
Ensure you generate a secure 32-byte string for the `ENCRYPTION_KEY` which is used for AES-256 encryption of user integrations (e.g. Gmail OAuth tokens).

### 3. Install Dependencies & Run Migrations
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Apply the latest database schemas
alembic upgrade head
```

### 4. Boot the Applications

**Start the FastAPI Server:**
```bash
source venv/bin/activate
uvicorn main:app --reload --port 8081
```

**Start the Celery Background Worker (Optional for Pending Approvals):**
```bash
source venv/bin/activate
celery -A celery_app worker --loglevel=info
```

## API Modules

### Webhook API
- `POST /bot/{user_id}`: Core telecom message entrypoint. Must include the `X-Hub-Signature-256` header.

### Provisioning API
- `POST /provision`: Internal endpoint for the Alter Go server to create managed profiles.

### Configuration API
Used by frontends for bot management:
- `POST /config/{user_id}/integrations/{service}/connect`: Securely vault integration secrets.
- `GET/PUT /config/{user_id}/instructions`: Set custom LLM prompting rules.
- `POST /config/{user_id}/approvals/{approval_id}/approve`: Unblock a pending tool action.
- `PUT /config/{user_id}/preferences/llm`: Hot-swap the underlying AI brain (e.g., `claude` or `gemini`).
