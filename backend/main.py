"""
main.py
-------
FastAPI application entry-point.

Endpoints
---------
POST /notifications          – receive a single notification from the Android app
POST /notifications/batch    – receive multiple notifications at once
GET  /notifications          – list stored notifications (for debugging)
POST /digest/trigger         – manually trigger a digest e-mail immediately
GET  /health                 – liveness probe
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

load_dotenv()

from email_sender import send_digest
from models import Notification
from notification_store import (
    clear_notifications,
    get_recent_notifications,
    store_notification,
)
from rag_engine import build_digest
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Digest scheduler started.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("Digest scheduler stopped.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PALM Messenger RAG",
    description=(
        "Receives Android notifications (WhatsApp, Telegram, …), stores them "
        "in a vector database, and periodically sends a RAG-generated digest "
        "to a configured e-mail address."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post(
    "/notifications",
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
def receive_notification(notification: Notification):
    """Store a single notification forwarded from the Android app."""
    if not notification.timestamp:
        notification.timestamp = datetime.now(timezone.utc).isoformat()
    doc_id = store_notification(notification)
    logger.info(
        "Stored notification id=%s app=%s sender=%s",
        doc_id,
        notification.app,
        notification.sender,
    )
    return {"id": doc_id, "status": "stored"}


@app.post(
    "/notifications/batch",
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
def receive_notifications_batch(notifications: List[Notification]):
    """Store multiple notifications in one request."""
    ids = []
    for notif in notifications:
        if not notif.timestamp:
            notif.timestamp = datetime.now(timezone.utc).isoformat()
        ids.append(store_notification(notif))
    logger.info("Stored batch of %d notifications.", len(ids))
    return {"ids": ids, "status": "stored"}


@app.get("/notifications", tags=["notifications"])
def list_notifications(limit: int = 50):
    """Return recently stored notifications (for debugging / monitoring)."""
    items = get_recent_notifications(limit=limit)
    return {"count": len(items), "notifications": items}


@app.post("/digest/trigger", tags=["digest"])
def trigger_digest():
    """
    Manually trigger a digest run – useful for testing or on-demand checks.
    Builds the RAG summary, sends the e-mail, and clears the store.
    """
    try:
        digest = build_digest()
        send_digest(digest)
        clear_notifications()
    except Exception as exc:
        logger.exception("Manual digest trigger failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    return {"status": "digest sent"}


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
