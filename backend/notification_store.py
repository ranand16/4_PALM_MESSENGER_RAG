"""
notification_store.py
---------------------
This module is the persistence layer for notifications.

It uses ChromaDB (a vector database) to store incoming notification text
plus metadata, so that later the RAG pipeline can retrieve and summarize it.
"""

# Keep type annotation behavior consistent across Python versions.
from __future__ import annotations

# Environment variable access.
import os
# UUID generation for unique document IDs.
import uuid
# Time utilities to create fallback UTC timestamps.
from datetime import datetime, timezone
# Type for function return annotations.
from typing import List

# ChromaDB main package.
import chromadb
# ChromaDB settings object for client configuration.
from chromadb.config import Settings

# Pydantic schema for incoming notification payloads.
from models import Notification


# Internal helper that returns the notifications collection handle.
def _get_collection() -> chromadb.Collection:
    # Directory where Chroma stores persistent data files.
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    # Create a persistent client connected to the local storage directory.
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    # Get existing collection or create it if missing.
    return client.get_or_create_collection(
        name="notifications",
        metadata={"hnsw:space": "cosine"},
    )


# Persist one notification and return the generated unique ID.
def store_notification(notification: Notification) -> str:
    """Store one notification row as document+metadata in ChromaDB."""
    # Resolve collection object.
    collection = _get_collection()
    # Generate random UUID string used as document primary key.
    doc_id = str(uuid.uuid4())
    # Use incoming timestamp when present; otherwise auto-generate current UTC.
    ts = notification.timestamp or datetime.now(timezone.utc).isoformat()

    # Build textual document that captures app, sender, and content in one line.
    document = (
        f"[{notification.app}] {notification.sender}: {notification.content}"
    )
    # Build metadata object for filtered queries or sorting in downstream logic.
    metadata = {
        "app": notification.app,
        "sender": notification.sender or "",
        "timestamp": ts,
    }

    # Insert exactly one item into Chroma using list-based API arguments.
    collection.add(documents=[document], metadatas=[metadata], ids=[doc_id])
    # Return generated ID so API caller can reference stored record.
    return doc_id


# Retrieve recent notifications, sorted by timestamp descending.
def get_recent_notifications(limit: int = 200) -> List[dict]:
    """Return recent notifications as simple dictionaries."""
    # Resolve collection from storage.
    collection = _get_collection()
    # Fetch all documents and metadata currently stored.
    result = collection.get(include=["documents", "metadatas"])
    # Build normalized output structure for callers.
    items = []
    # Pair each document with its matching metadata payload.
    for doc, meta in zip(result["documents"], result["metadatas"]):
        # Store each record as a dict with explicit keys.
        items.append({"document": doc, "metadata": meta})
    # Chroma order is not guaranteed, so sort manually by timestamp (newest first).
    items.sort(
        key=lambda x: x["metadata"].get("timestamp", ""), reverse=True
    )
    # Apply caller-provided limit.
    return items[:limit]


# Remove all stored notifications after digest is delivered.
def clear_notifications() -> None:
    """Delete the notifications collection from ChromaDB."""
    # Resolve persistence directory from environment (or default).
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
    # Create client pointing at existing persistent Chroma store.
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    # Drop the whole collection to clear processed notification history.
    client.delete_collection("notifications")
