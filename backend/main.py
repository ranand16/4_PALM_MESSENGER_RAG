"""
main.py
-------
This file is the backend entry point.

In plain words, it does these jobs:
1) Starts a FastAPI web server.
2) Fetches data from configured services such as Email and Telegram.
3) Stores fetched items for later AI summarization.
4) Exposes endpoints for health checks, sync, and manual digest triggering.
5) Starts and stops a background scheduler with the app lifecycle.
"""

# This future import lets us use modern type annotations consistently.
from __future__ import annotations

# Standard library logging for structured server logs.
import logging
# Standard library os for reading environment variables.
import os
# Context manager helper to define app startup and shutdown logic.
from contextlib import asynccontextmanager
# Datetime utilities to generate timezone-aware ISO timestamps.
from datetime import datetime, timezone
# Generic type for lists used in request bodies.
from typing import List

# Loads variables from a .env file into process environment.
from dotenv import load_dotenv
# FastAPI primitives used to build APIs and raise HTTP errors.
from fastapi import FastAPI, HTTPException, status

# Reads .env early so all modules can access required configuration.
load_dotenv()

# Sends digest e-mails using SMTP.
from email_sender import send_digest
# Pydantic model describing a notification payload.
from models import Notification
# Storage functions for persisting and reading notifications.
from notification_store import (
    clear_notifications,
    get_recent_notifications,
    store_notification,
)
# AI pipeline that turns stored notifications into a digest.
from rag_engine import build_digest
# Service orchestrator that fetches new email and Telegram data.
from agents.orchestrator import sync_services
# Scheduler factory to create periodic digest jobs.
from scheduler import create_scheduler

# Configure log level and log format globally for this process.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
# Create a module-level logger so messages are easy to filter by module name.
logger = logging.getLogger(__name__)


# Lifespan function is called by FastAPI at app startup and shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create scheduler instance (but not yet running).
    scheduler = create_scheduler()
    # Start the background scheduler so cron jobs begin executing.
    scheduler.start()
    # Log startup event for observability.
    logger.info("Digest scheduler started.")
    # Yield control back to FastAPI while app is running.
    yield
    # Stop scheduler gracefully during shutdown.
    scheduler.shutdown(wait=False)
    # Log shutdown event for observability.
    logger.info("Digest scheduler stopped.")


# Create the FastAPI application object.
app = FastAPI(
    # Human-readable API title shown in docs.
    title="PALM Messenger RAG",
    # High-level description shown in OpenAPI/Swagger docs.
    description=(
        "Fetches new items from configured services like Email and Telegram, "
        "stores them in a vector database, and periodically sends a RAG-generated "
        "digest to a configured e-mail address."
    ),
    # Semantic API version.
    version="1.0.0",
    # Attach startup/shutdown lifecycle hook.
    lifespan=lifespan,
)


# Simple liveness endpoint used by monitors or load balancers.
@app.get("/health", tags=["system"])
def health():
    # Return current status and UTC timestamp for easy diagnostics.
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# Endpoint to trigger a sync run for all configured services.
@app.post("/sync", tags=["sync"])
def trigger_sync():
    """Fetch new data from configured services and store it for later digest generation."""
    try:
        result = sync_services()
    except Exception as exc:
        logger.exception("Sync endpoint failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return {
        "status": "synced",
        "services_synced": result["services_synced"],
        "messages_fetched": result["messages_fetched"],
    }


# Endpoint that returns latest stored notifications.
@app.get("/notifications", tags=["notifications"])
def list_notifications(limit: int = 50):
    """List recent notifications; mostly useful for debugging and inspection."""
    # Query storage layer with requested limit.
    items = get_recent_notifications(limit=limit)
    # Return count plus full item payload.
    return {"count": len(items), "notifications": items}


# Endpoint to manually trigger digest generation and sending.
@app.post("/digest/trigger", tags=["digest"])
def trigger_digest():
    """
    Run digest pipeline right now.

    Typical flow:
    1) Build digest from stored notifications.
    2) Send digest by e-mail.
    3) Clear stored notifications to avoid duplicate digests.
    """
    try:
        # Build AI-generated digest text.
        digest = build_digest()
        # Send digest to configured recipient.
        send_digest(digest)
        # Clear data so processed notifications are not re-sent.
        clear_notifications()
    except Exception as exc:
        # Log full stack trace so failures can be investigated.
        logger.exception("Manual digest trigger failed.")
        # Return controlled HTTP 500 response to API caller.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    # Success response when all three steps complete.
    return {"status": "digest sent"}


# Local development launcher: `python main.py`.
if __name__ == "__main__":
    # Import here to avoid dependency loading when module is imported elsewhere.
    import uvicorn

    # Start ASGI server with host/port from environment and auto-reload on edits.
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
