# PALM Messenger RAG

> **Consolidate Email and Telegram into one smart digest system.**

This project no longer depends on an Android notification forwarder. Instead, it fetches new items directly from configured services, stores them in a unified backend, and generates an AI-powered digest using Google Gemini.

---

## Architecture

```
Email Service  ──┐
                 ├─→ Service Agents ──→ ChromaDB ──→ Gemini Digest ──→ E-mail Delivery
Telegram Service ─┘
```

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| **Service config** | `backend/config.json` | List of enabled services and fetch settings |
| **Service connectors** | `backend/mcp_servers/` | Email + Telegram fetching logic |
| **Orchestrator** | `backend/agents/orchestrator.py` | Spawns one agent per service and stores results |
| **Notification store** | `backend/notification_store.py` | ChromaDB-backed persistence layer |
| **RAG engine** | `backend/rag_engine.py` | Google Gemini summary builder |
| **E-mail sender** | `backend/email_sender.py` | SMTP e-mail dispatch (plain-text + HTML) |
| **Scheduler** | `backend/scheduler.py` | Optional periodic digest runner |

---

## Quick Start

### 1 — Backend (Python)

**Prerequisites:** Python 3.10+

```bash
cd backend
cp .env.example .env          # fill in API keys, SMTP credentials, and source settings
pip install -r requirements.txt
python main.py
```

The server listens on `http://0.0.0.0:8000` by default.

**Interactive API docs:** open `http://localhost:8000/docs` in a browser.

#### Service configuration

Services are configured in `backend/config.json`. Each item is a separate service agent. The current example includes:

- `personal_email` — fetches new e-mail from IMAP
- `personal_telegram` — fetches new Telegram messages from your account

#### Environment variables (`.env`)

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio API key (for Gemini) |
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (default `587`) |
| `SMTP_USER` | SMTP login username |
| `SMTP_PASSWORD` | SMTP login password / App Password |
| `EMAIL_FROM` | Sender address shown in digest e-mail |
| `EMAIL_TO` | Delivery recipient address |
| `CHROMA_PERSIST_DIR` | Directory for ChromaDB data (default `./chroma_db`) |
| `HOST` | Server bind address (default `0.0.0.0`) |
| `PORT` | Server port (default `8000`) |
| `EMAIL_IMAP_HOST` | IMAP server hostname for personal email |
| `EMAIL_ADDRESS` | Email address to fetch from |
| `EMAIL_PASSWORD` | Password or app password for the inbox |
| `EMAIL_MAILBOX` | Mailbox to scan (default `INBOX`) |
| `TELEGRAM_API_ID` | Telegram API id |
| `TELEGRAM_API_HASH` | Telegram API hash |
| `TELEGRAM_SESSION_FILE` | Telegram session file path |

#### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `POST` | `/sync` | Fetch new data from all configured services |
| `GET` | `/notifications` | List stored notifications |
| `POST` | `/digest/trigger` | Manually trigger a digest e-mail |

---

## How to run a sync

Trigger a sync for Email and Telegram data using:

```bash
curl -X POST http://localhost:8000/sync
```

That call spawns one agent per enabled service, collects all new items, and stores them in ChromaDB.

## How to generate the digest

Use the digest trigger endpoint:

```bash
curl -X POST http://localhost:8000/digest/trigger
```

This builds a Gemini-powered summary from stored items, sends it via SMTP, and clears the storage.

---

## Notes

- The Android folder has been removed in favor of direct service connectors.
- The system is now driven by `backend/config.json` and service agent logic.
- New services can be added by creating a new connector in `backend/mcp_servers/` and registering it in `backend/agents/orchestrator.py`.

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt pytest httpx
pytest ../tests/test_backend.py -v
```

---

## Security

Keep your email and Telegram credentials secret. Do not commit `.env` or `backend/config.json` with real secrets into version control.

