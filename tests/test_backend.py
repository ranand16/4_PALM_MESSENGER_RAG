"""
tests/test_backend.py
---------------------
Unit tests for the PALM Messenger RAG backend.

Run with:
    cd backend && pip install -r requirements.txt pytest httpx
    pytest ../tests/test_backend.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure backend/ is on the Python path ─────────────────────────────────────
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class TestNotificationModel:
    def test_required_fields(self):
        from models import Notification

        n = Notification(app="WhatsApp", content="Hello!")
        assert n.app == "WhatsApp"
        assert n.content == "Hello!"
        assert n.sender is None
        assert n.timestamp is None

    def test_all_fields(self):
        from models import Notification

        n = Notification(
            app="Telegram",
            sender="Alice",
            content="Meeting at 3pm",
            timestamp="2024-01-01T10:00:00Z",
        )
        assert n.sender == "Alice"
        assert n.timestamp == "2024-01-01T10:00:00Z"


# ---------------------------------------------------------------------------
# email_sender – unit-test _to_html without sending real e-mail
# ---------------------------------------------------------------------------

class TestEmailSender:
    def test_to_html_contains_digest(self):
        from email_sender import _to_html

        html = _to_html("Hello world", "2024-01-01 12:00 UTC")
        assert "Hello world" in html
        assert "2024-01-01 12:00 UTC" in html
        assert "<!DOCTYPE html>" in html

    def test_to_html_escapes_special_chars(self):
        from email_sender import _to_html

        html = _to_html("<script>alert('xss')</script>", "now")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# notification_store – mock ChromaDB
# ---------------------------------------------------------------------------

class TestNotificationStore:
    @patch("notification_store.chromadb.PersistentClient")
    def test_store_notification_returns_id(self, mock_client_cls):
        mock_collection = MagicMock()
        mock_collection.add = MagicMock()
        mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

        from models import Notification
        import notification_store

        with patch.object(notification_store, "_get_collection", return_value=mock_collection):
            doc_id = notification_store.store_notification(
                Notification(app="WhatsApp", sender="Bob", content="Hi there!")
            )

        assert isinstance(doc_id, str) and len(doc_id) > 0
        mock_collection.add.assert_called_once()

    @patch("notification_store.chromadb.PersistentClient")
    def test_get_recent_notifications_sorted(self, mock_client_cls):
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "documents": ["[WhatsApp] Alice: Hi", "[Telegram] Bob: Hey"],
            "metadatas": [
                {"app": "WhatsApp", "sender": "Alice", "timestamp": "2024-01-01T10:00:00"},
                {"app": "Telegram", "sender": "Bob",   "timestamp": "2024-01-01T11:00:00"},
            ],
        }
        mock_client_cls.return_value.get_or_create_collection.return_value = mock_collection

        import notification_store

        with patch.object(notification_store, "_get_collection", return_value=mock_collection):
            items = notification_store.get_recent_notifications(limit=10)

        # Most-recent first (Telegram at 11:00 before WhatsApp at 10:00)
        assert items[0]["metadata"]["app"] == "Telegram"
        assert items[1]["metadata"]["app"] == "WhatsApp"


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

class TestFastAPIRoutes:
    @pytest.fixture(autouse=True)
    def _patch_scheduler(self, monkeypatch):
        """Prevent the real APScheduler from starting during tests."""
        import scheduler as sched_module
        monkeypatch.setattr(
            sched_module,
            "create_scheduler",
            lambda: MagicMock(start=MagicMock(), shutdown=MagicMock()),
        )

    def test_health(self):
        from fastapi.testclient import TestClient
        import main as main_module
        client = TestClient(main_module.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_receive_notification(self):
        mock_store = MagicMock(return_value="test-id-123")
        with patch("main.store_notification", mock_store):
            from fastapi.testclient import TestClient
            import main as main_module
            client = TestClient(main_module.app)
            response = client.post(
                "/notifications",
                json={"app": "WhatsApp", "sender": "Alice", "content": "Hello"},
            )
        assert response.status_code == 201
        assert response.json()["status"] == "stored"

    def test_list_notifications(self):
        mock_items = [
            {
                "document": "[WhatsApp] Alice: Hello",
                "metadata": {
                    "app": "WhatsApp",
                    "sender": "Alice",
                    "timestamp": "2024-01-01T10:00:00",
                },
            }
        ]
        with patch("main.get_recent_notifications", return_value=mock_items):
            from fastapi.testclient import TestClient
            import main as main_module
            client = TestClient(main_module.app)
            response = client.get("/notifications?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_receive_notification_batch(self):
        mock_store = MagicMock(side_effect=["id-1", "id-2"])
        with patch("main.store_notification", mock_store):
            from fastapi.testclient import TestClient
            import main as main_module
            client = TestClient(main_module.app)
            response = client.post(
                "/notifications/batch",
                json=[
                    {"app": "WhatsApp", "sender": "Alice", "content": "Hello"},
                    {"app": "Telegram", "sender": "Bob", "content": "Hey"},
                ],
            )
        assert response.status_code == 201
        assert response.json()["status"] == "stored"
        assert len(response.json()["ids"]) == 2
