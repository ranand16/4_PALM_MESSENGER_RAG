"""
notification_store.py
---------------------
Persists incoming notifications in ChromaDB so the RAG engine can retrieve
relevant context when composing the e-mail digest.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import List

import chromadb
from chromadb.config import Settings

from models import Notification


def _get_collection() -> chromadb.Collection:
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name="notifications",
        metadata={"hnsw:space": "cosine"},
    )


def store_notification(notification: Notification) -> str:
    """Persist a single notification and return its generated ID."""
    collection = _get_collection()
    doc_id = str(uuid.uuid4())
    ts = notification.timestamp or datetime.now(timezone.utc).isoformat()

    document = (
        f"[{notification.app}] {notification.sender}: {notification.content}"
    )
    metadata = {
        "app": notification.app,
        "sender": notification.sender or "",
        "timestamp": ts,
    }

    collection.add(documents=[document], metadatas=[metadata], ids=[doc_id])
    return doc_id


def get_recent_notifications(limit: int = 200) -> List[dict]:
    """Return the most-recently stored notifications as plain dicts."""
    collection = _get_collection()
    result = collection.get(include=["documents", "metadatas"])
    items = []
    for doc, meta in zip(result["documents"], result["metadatas"]):
        items.append({"document": doc, "metadata": meta})
    # ChromaDB doesn't guarantee insertion order; sort by timestamp descending
    items.sort(
        key=lambda x: x["metadata"].get("timestamp", ""), reverse=True
    )
    return items[:limit]


def clear_notifications() -> None:
    """Delete all stored notifications (called after a digest is sent)."""
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    client.delete_collection("notifications")
