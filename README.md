# PALM Messenger RAG

Scans your Android phone's WhatsApp, Telegram, Signal (and other app) notifications, processes them through a RAG pipeline (Ollama + Qdrant), and sends consolidated AI-summarized digest emails to your personal inbox.

## Architecture

```
┌─────────────────────────┐
│   Android App (Kotlin)  │
│   NotificationListener  │
│   + WorkManager sync    │
└──────────┬──────────────┘
           │ POST /api/notifications
           ▼
┌─────────────────────────┐     ┌──────────────┐
│   Go Backend (net/http) │◄───►│   Qdrant     │
│                         │     │   (Docker)   │
│   • Ingest + Embed      │     └──────────────┘
│   • RAG Summarize       │     ┌──────────────┐
│   • Email Digest        │◄───►│   Ollama     │
│   • Scheduler           │     │   (Docker)   │
└─────────────────────────┘     └──────────────┘
```

## Components

| Component | Language | Purpose |
|-----------|----------|---------|
| `backend/` | Go | REST API, RAG pipeline, email digest, scheduler |
| `android/` | Kotlin | Captures phone notifications and syncs to backend |
| Qdrant | Docker | Vector database for notification embeddings |
| Ollama | Docker | LLM for embeddings (`nomic-embed-text`) and summarization (`mistral:7b`) |

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your values:
#   - SMTP credentials (Gmail App Password)
#   - API_KEY (shared secret for Android app auth)
#   - EMAIL_TO (your email for receiving digests)
```

**Gmail App Password setup:**
1. Go to https://myaccount.google.com/apppasswords
2. Generate a new app password for "Mail"
3. Use that password as `SMTP_PASSWORD` in `.env`

### 2. Start Infrastructure

```bash
docker-compose up -d
```

This starts:
- **Qdrant** on ports 6333 (REST) / 6334 (gRPC)
- **Ollama** on port 11434 (auto-pulls `nomic-embed-text` and `mistral:7b`)
- **Go backend** on port 8000

### 3. Verify

```bash
# Health check
curl http://localhost:8000/health

# Test ingest (simulated notification)
curl -X POST http://localhost:8000/api/notifications \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{
    "notifications": [
      {
        "package_name": "com.whatsapp",
        "title": "John",
        "text": "Hey, are we still meeting at 3pm?",
        "timestamp": 1711612800000
      },
      {
        "package_name": "org.telegram.messenger",
        "title": "Work Group",
        "text": "Deployment scheduled for tonight at 10pm",
        "timestamp": 1711613400000
      }
    ]
  }'

# Preview digest (HTML)
curl "http://localhost:8000/api/digest/preview?hours=24&api_key=YOUR_API_KEY"

# Trigger digest email manually
curl -X POST "http://localhost:8000/api/digest/send?hours=24" \
  -H "X-API-Key: YOUR_API_KEY"

# View recent notifications
curl "http://localhost:8000/api/notifications/recent?hours=24&api_key=YOUR_API_KEY"
```

### 4. Install Android App

1. Open `android/` folder in Android Studio
2. Build and install on your phone
3. Open the app → configure:
   - **Backend URL**: `http://<your-server-ip>:8000`
   - **API Key**: same value as `API_KEY` in `.env`
4. Tap **"Grant Notification Access"** → enable PALM RAG
5. Notifications from WhatsApp, Telegram, Signal, etc. will now be captured and synced

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check (Qdrant + Ollama status) |
| `POST` | `/api/notifications` | API Key | Ingest notification batch |
| `GET` | `/api/digest/preview?hours=N` | API Key | Preview digest as HTML |
| `POST` | `/api/digest/send?hours=N` | API Key | Generate and send digest email |
| `GET` | `/api/notifications/recent?hours=N` | API Key | List recent stored notifications |

Auth: pass `X-API-Key` header or `?api_key=` query param.

## How It Works

1. **Capture**: Android `NotificationListenerService` intercepts notifications from whitelisted apps
2. **Queue**: Notifications are stored in local Room DB, synced via WorkManager every 15 minutes
3. **Embed**: Backend embeds notification text using Ollama's `nomic-embed-text` (768-dim vectors)
4. **Store**: Vectors + metadata stored in Qdrant collection with timestamp and app_name indexes
5. **Summarize**: On schedule (or manual trigger), the RAG pipeline:
   - Retrieves recent notifications from Qdrant (timestamp filter)
   - Groups by app
   - For each group, finds semantically similar older messages for context
   - Generates concise per-group summary using `mistral:7b`
6. **Email**: Renders HTML digest with AI summaries and sends via SMTP

## Scheduler

The backend runs an automatic digest scheduler:
- Default: every **2 hours** between **9:00 AM – 7:00 PM**
- Configure via `DIGEST_INTERVAL_HOURS`, `DIGEST_START_HOUR`, `DIGEST_END_HOUR` in `.env`

## Supported Apps

Default whitelist (configurable in Android app):
- WhatsApp / WhatsApp Business
- Telegram
- Signal
- Google Messages
- Facebook Messenger
- Instagram
- Slack
- Discord

## Local Development (without Docker)

```bash
# Start Qdrant
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Start Ollama (install from https://ollama.com)
ollama serve
ollama pull nomic-embed-text
ollama pull mistral:7b

# Run backend
cd backend
cp ../.env.example ../.env  # edit with local values (QDRANT_HOST=localhost, OLLAMA_URL=http://localhost:11434)
go run .
```

## Project Structure

```
├── docker-compose.yml          # Qdrant + Ollama + Backend
├── .env.example                # Environment variables template
├── backend/
│   ├── main.go                 # Entry point, HTTP server, graceful shutdown
│   ├── Dockerfile              # Multi-stage Go build
│   ├── go.mod / go.sum
│   ├── api/handlers.go         # HTTP handlers + auth middleware
│   ├── config/config.go        # Environment config loader
│   ├── email/
│   │   ├── service.go          # SMTP email sender with STARTTLS
│   │   └── templates/digest.html  # HTML email template
│   ├── models/models.go        # Notification, Digest data types
│   ├── ollama/client.go        # Ollama REST client (embed + chat)
│   ├── rag/pipeline.go         # RAG orchestration (ingest + summarize)
│   ├── scheduler/scheduler.go  # Periodic digest scheduler
│   └── store/qdrant.go         # Qdrant gRPC client wrapper
└── android/
    ├── app/
    │   ├── build.gradle
    │   └── src/main/
    │       ├── AndroidManifest.xml
    │       ├── java/com/palmrag/
    │       │   ├── NotificationListener.kt   # Notification capture service
    │       │   ├── api/ApiClient.kt           # Retrofit HTTP client
    │       │   ├── db/
    │       │   │   ├── AppDatabase.kt         # Room database
    │       │   │   ├── NotificationDao.kt     # Database queries
    │       │   │   └── NotificationEntity.kt  # DB entity
    │       │   ├── sync/NotificationSyncWorker.kt  # Background sync worker
    │       │   └── ui/SettingsActivity.kt     # Settings UI
    │       └── res/
    │           ├── layout/activity_settings.xml
    │           └── values/strings.xml
    ├── build.gradle
    ├── settings.gradle
    └── gradle.properties
```
