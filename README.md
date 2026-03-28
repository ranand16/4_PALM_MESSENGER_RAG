# PALM Messenger RAG

> **Read your WhatsApp, Telegram & other messaging notifications from the office — without your phone.**

This project forwards Android messaging-app notifications to a Python backend that uses a RAG (Retrieval-Augmented Generation) pipeline powered by Google Gemini to compose a consolidated e-mail digest, delivered on a configurable schedule.

---

## Architecture

```
Android Phone                    PC / Server                       Your Inbox
─────────────────────────────    ───────────────────────────────   ──────────────
 WhatsApp / Telegram / Signal ──► FastAPI server (POST /notifications)
                                        │
                                   ChromaDB (vector store)
                                        │
                                   Google Gemini (map-reduce RAG)
                                        │
                                   APScheduler (cron) ──────────────► E-mail digest
```

### Components

| Component | Location | Description |
|-----------|----------|-------------|
| **Android app** | `android/` | Kotlin `NotificationListenerService` that captures notifications and POSTs them to the backend |
| **FastAPI server** | `backend/main.py` | REST API that receives and stores notifications |
| **Notification store** | `backend/notification_store.py` | ChromaDB-backed persistence layer |
| **RAG engine** | `backend/rag_engine.py` | Google Gemini map-reduce digest builder |
| **E-mail sender** | `backend/email_sender.py` | SMTP e-mail dispatch (plain-text + HTML) |
| **Scheduler** | `backend/scheduler.py` | APScheduler cron job (default: every hour) |

---

## Quick Start

### 1 — Backend (Python)

**Prerequisites:** Python 3.10+

```bash
cd backend
cp .env.example .env          # fill in your API key, SMTP credentials, etc.
pip install -r requirements.txt
python main.py
```

The server listens on `http://0.0.0.0:8000` by default.

**Interactive API docs:** open `http://localhost:8000/docs` in a browser.

#### Environment variables (`.env`)

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio API key (for Gemini) |
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (default `587`) |
| `SMTP_USER` | SMTP login username |
| `SMTP_PASSWORD` | SMTP login password / App Password |
| `EMAIL_FROM` | Sender address shown in the digest e-mail |
| `EMAIL_TO` | Recipient address (your office e-mail) |
| `DIGEST_CRON_HOUR` | Cron hour expression (default `*/1` = every hour) |
| `DIGEST_CRON_MINUTE` | Cron minute expression (default `0`) |
| `CHROMA_PERSIST_DIR` | Directory for ChromaDB data (default `./chroma_db`) |
| `HOST` | Server bind address (default `0.0.0.0`) |
| `PORT` | Server port (default `8000`) |

#### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `POST` | `/notifications` | Store a single notification |
| `POST` | `/notifications/batch` | Store multiple notifications |
| `GET` | `/notifications` | List stored notifications |
| `POST` | `/digest/trigger` | Manually trigger a digest e-mail |

### 2 — Android App

**Prerequisites:** Android Studio + JDK 17, Android device running API 24+

```bash
cd android
# open in Android Studio, then Build → Make Project
# install the APK on your Android phone
```

**Setup on the phone:**

1. Open the **PALM Messenger RAG** app.
2. Enter your backend server URL (e.g. `http://192.168.1.10:8000` — your office PC's local IP, or a publicly reachable URL).
3. Tap **Save**.
4. Tap **Open Notification Access Settings** and grant permission to the app.

Once permission is granted the app runs silently in the background. Every WhatsApp, Telegram, Signal, Viber, or Messenger notification will be forwarded to the backend automatically.

> **Tip:** Use [ngrok](https://ngrok.com/) or a VPN to expose your local server to the internet so the phone can reach it over a mobile data connection.

---

## Running Tests

```bash
pip install pytest httpx
pytest tests/ -v
```

---

## Gmail Setup

1. Enable **2-Step Verification** on your Google account.
2. Go to **My Account → Security → App Passwords**.
3. Generate an App Password for "Mail / Other device".
4. Use that 16-character password as `SMTP_PASSWORD` in your `.env`.

---

## Supported Apps

The Android app currently monitors notifications from:

- WhatsApp & WhatsApp Business
- Telegram
- Signal
- Viber
- Facebook Messenger

To add more apps, add their package names to `MONITORED_PACKAGES` in `NotificationForwarderService.kt`.

