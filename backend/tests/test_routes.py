"""
Route tests — health endpoint, eat-in query, session create, feedback.
Uses FastAPI TestClient with mocked external dependencies.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthRoute:
    def test_health_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_and_version(self):
        resp = client.get("/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Eat-in query endpoint
# ---------------------------------------------------------------------------


class TestEatInRoute:

    @patch("routes.eat_in.create_session", new_callable=AsyncMock)
    @patch("routes.eat_in.add_message", new_callable=AsyncMock)
    @patch("routes.eat_in.increment_query_count", new_callable=AsyncMock)
    @patch("routes.eat_in.run_eat_in_pipeline", new_callable=AsyncMock)
    def test_valid_query_returns_200(
        self, mock_pipeline, mock_inc, mock_add_msg, mock_create_session
    ):
        mock_create_session.return_value = {"session_id": "sess-123"}
        mock_add_msg.return_value = {"message_id": "msg-001"}
        mock_pipeline.return_value = {
            "generated_text": "Here are your recipes.",
            "results": [],
            "debug": {},
            "pipeline_status": "ok",
        }

        resp = client.post(
            "/api/eat-in/query",
            json={"user_id": "user-001", "query": "I want Italian pasta"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "generated_text" in data
        assert "pipeline_status" in data

    def test_missing_user_id_returns_422(self):
        """Missing user_id → Pydantic validation error (422)."""
        resp = client.post(
            "/api/eat-in/query",
            json={"query": "I want pasta"},
        )
        assert resp.status_code == 422

    def test_missing_query_returns_422(self):
        """Missing query → Pydantic validation error (422)."""
        resp = client.post(
            "/api/eat-in/query",
            json={"user_id": "user-001"},
        )
        assert resp.status_code == 422

    @patch("routes.eat_in.create_session", new_callable=AsyncMock)
    @patch("routes.eat_in.add_message", new_callable=AsyncMock)
    @patch("routes.eat_in.increment_query_count", new_callable=AsyncMock)
    @patch("routes.eat_in.run_eat_in_pipeline", new_callable=AsyncMock)
    def test_empty_query_string_still_processes(
        self, mock_pipeline, mock_inc, mock_add_msg, mock_create_session
    ):
        """Empty string query → should still be accepted by the route (pipeline handles it)."""
        mock_create_session.return_value = {"session_id": "sess-456"}
        mock_add_msg.return_value = {"message_id": "msg-002"}
        mock_pipeline.return_value = {
            "generated_text": "Please tell me what you'd like to cook.",
            "results": [],
            "debug": {},
            "pipeline_status": "off_topic",
        }

        resp = client.post(
            "/api/eat-in/query",
            json={"user_id": "user-001", "query": ""},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Sessions endpoint
# ---------------------------------------------------------------------------


class TestSessionsRoute:

    @patch("routes.sessions.session_manager.create_session", new_callable=AsyncMock)
    def test_create_session_returns_200(self, mock_create):
        mock_create.return_value = {"session_id": "sess-789", "mode": "eat_in"}

        resp = client.post(
            "/api/sessions/",
            json={"user_id": "user-001", "mode": "eat_in"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data

    @patch("routes.sessions.session_manager.create_session", new_callable=AsyncMock)
    def test_create_session_503_on_failure(self, mock_create):
        mock_create.side_effect = Exception("DB unavailable")

        resp = client.post(
            "/api/sessions/",
            json={"user_id": "user-001"},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Feedback endpoint
# ---------------------------------------------------------------------------


class TestFeedbackRoute:

    @patch("routes.feedback.feedback_service.record_feedback", new_callable=AsyncMock)
    def test_valid_feedback_returns_200(self, mock_record):
        mock_record.return_value = {"feedback_id": "fb-001"}

        resp = client.post(
            "/api/feedback/",
            json={
                "user_id": "user-001",
                "result_type": "recipe",
                "result_reference": "recipe-uuid-001",
                "feedback_type": "liked",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"

    def test_missing_required_fields_returns_422(self):
        """Missing required fields → validation error."""
        resp = client.post(
            "/api/feedback/",
            json={"user_id": "user-001"},
        )
        assert resp.status_code == 422

    @patch("routes.feedback.feedback_service.record_feedback", new_callable=AsyncMock)
    def test_feedback_503_on_service_failure(self, mock_record):
        mock_record.side_effect = Exception("DB unavailable")

        resp = client.post(
            "/api/feedback/",
            json={
                "user_id": "user-001",
                "result_type": "recipe",
                "result_reference": "recipe-uuid-001",
                "feedback_type": "liked",
            },
        )
        assert resp.status_code == 503
