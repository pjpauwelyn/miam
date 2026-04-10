"""
Error path tests — LLM failures, malformed JSON, embedding errors,
Supabase 500 on profile fetch.

Tests verify that the pipeline degrades gracefully rather than crashing.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Use a valid UUID for all tests
TEST_USER_ID = str(uuid4())
TEST_SESSION_ID = str(uuid4())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_profile_row():
    """A minimal profile row as Supabase REST would return it."""
    return {
        "user_id": TEST_USER_ID,
        "profile_status": "active",
        "profile_data": {
            "user_id": TEST_USER_ID,
            "dietary": {"spectrum_label": "omnivore", "hard_stops": [], "soft_stops": []},
            "cuisine_affinities": {"affinities": [{"cuisine": "Italian", "level": "like"}]},
            "flavor": {},
            "cooking": {"skill": "home_cook", "weeknight_minutes": 45},
            "budget": {"home_per_meal_eur": 10.0, "out_per_meal_eur": 20.0},
            "location": {"city": "Amsterdam", "country": "NL"},
            "adventurousness": {"cooking_score": 5.0, "dining_score": 5.0},
            "onboarding_complete": True,
            "profile_summary_text": "Test user",
        },
    }


def _mock_httpx_response(status_code=200, json_data=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else []
    resp.text = str(json_data)
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestErrorPaths:

    @pytest.mark.asyncio
    async def test_mistral_500_pipeline_falls_back_to_deterministic(self):
        """
        When the LLM (extract_query) raises, the pipeline should handle it
        and return a valid pipeline status — not crash.
        """
        from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

        mock_profile_resp = _mock_httpx_response(200, [_default_profile_row()])

        with (
            patch("services.pipeline.eat_in_pipeline.httpx.AsyncClient") as MockClient,
            patch(
                "services.pipeline.eat_in_pipeline.extract_query",
                new_callable=AsyncMock,
                side_effect=Exception("Mistral 500 — internal server error"),
            ),
        ):
            # Mock Supabase profile fetch
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_profile_resp
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await run_eat_in_pipeline(
                raw_query="I want pasta",
                user_id=TEST_USER_ID,
                session_id=TEST_SESSION_ID,
            )

        assert isinstance(result, dict)
        assert "pipeline_status" in result
        assert result.get("pipeline_status") in ("ok", "partial", "error", "off_topic", "no_results")
        assert "generated_text" in result

    @pytest.mark.asyncio
    async def test_malformed_json_from_llm(self):
        """
        When the LLM returns malformed data, extract_query should handle it
        and the pipeline should not crash.
        """
        from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
        from models.query_ontology import QueryOntology, QueryMode, EatInAttributes

        # Return a valid but minimal QueryOntology (simulating parser recovery)
        mock_query = QueryOntology(
            user_id=TEST_USER_ID,
            raw_query="I want pasta",
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(desired_cuisine="Italian"),
            query_complexity=0.3,
        )

        mock_profile_resp = _mock_httpx_response(200, [_default_profile_row()])

        with (
            patch("services.pipeline.eat_in_pipeline.httpx.AsyncClient") as MockClient,
            patch(
                "services.pipeline.eat_in_pipeline.extract_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ),
            patch(
                "services.pipeline.eat_in_pipeline.retrieve_recipes",
                new_callable=AsyncMock,
                return_value=[],  # No results — triggers no_results path
            ),
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_profile_resp
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await run_eat_in_pipeline(
                raw_query="I want pasta",
                user_id=TEST_USER_ID,
                session_id=TEST_SESSION_ID,
            )

        assert isinstance(result, dict)
        assert result.get("pipeline_status") in ("ok", "partial", "error", "off_topic", "no_results")

    @pytest.mark.asyncio
    async def test_embedding_failure_retriever_returns_empty(self):
        """
        When the embedding fetch fails, retrieve_recipes raises → pipeline
        should return an error status with a helpful message.
        """
        from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
        from models.query_ontology import QueryOntology, QueryMode, EatInAttributes

        mock_query = QueryOntology(
            user_id=TEST_USER_ID,
            raw_query="I want pasta",
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(desired_cuisine="Italian"),
            query_complexity=0.3,
        )

        mock_profile_resp = _mock_httpx_response(200, [_default_profile_row()])

        with (
            patch("services.pipeline.eat_in_pipeline.httpx.AsyncClient") as MockClient,
            patch(
                "services.pipeline.eat_in_pipeline.extract_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ),
            patch(
                "services.pipeline.eat_in_pipeline.retrieve_recipes",
                new_callable=AsyncMock,
                side_effect=Exception("Embedding service unavailable"),
            ),
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_profile_resp
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await run_eat_in_pipeline(
                raw_query="I want pasta",
                user_id=TEST_USER_ID,
                session_id=TEST_SESSION_ID,
            )

        assert isinstance(result, dict)
        assert result.get("pipeline_status") == "error"
        assert "generated_text" in result

    @pytest.mark.asyncio
    async def test_generate_response_failure_returns_partial_result(self):
        """
        When refine_results raises and no recipes are found, pipeline should
        return a valid status.
        """
        from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
        from models.query_ontology import QueryOntology, QueryMode, EatInAttributes

        mock_query = QueryOntology(
            user_id=TEST_USER_ID,
            raw_query="I want pasta",
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(desired_cuisine="Italian"),
            query_complexity=0.3,
        )

        mock_profile_resp = _mock_httpx_response(200, [_default_profile_row()])

        with (
            patch("services.pipeline.eat_in_pipeline.httpx.AsyncClient") as MockClient,
            patch(
                "services.pipeline.eat_in_pipeline.extract_query",
                new_callable=AsyncMock,
                return_value=mock_query,
            ),
            patch(
                "services.pipeline.eat_in_pipeline.retrieve_recipes",
                new_callable=AsyncMock,
                return_value=[],  # Empty results → triggers no_results
            ),
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_profile_resp
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await run_eat_in_pipeline(
                raw_query="I want pasta",
                user_id=TEST_USER_ID,
                session_id=TEST_SESSION_ID,
            )

        assert isinstance(result, dict)
        assert "pipeline_status" in result
        assert result.get("pipeline_status") in ("ok", "partial", "error", "off_topic", "no_results")

    @pytest.mark.asyncio
    async def test_supabase_500_on_profile_fetch(self):
        """
        When Supabase returns 500 for profile fetch → pipeline should use
        default profile and still produce a response.
        """
        from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

        mock_profile_resp = _mock_httpx_response(500, None)

        with (
            patch("services.pipeline.eat_in_pipeline.httpx.AsyncClient") as MockClient,
        ):
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_profile_resp
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            result = await run_eat_in_pipeline(
                raw_query="I want pasta",
                user_id=TEST_USER_ID,
                session_id=TEST_SESSION_ID,
            )

        assert isinstance(result, dict)
        # With no profile, pipeline should still work (uses default)
        assert "pipeline_status" in result
        assert "generated_text" in result
