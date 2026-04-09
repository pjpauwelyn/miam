"""
LLM router tests — verify routing table and basic call mechanics.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.llm_router import (
    LLMOperation,
    MODEL_ROUTING,
    call_llm,
    call_llm_json,
    TIMEOUT_SECONDS,
)


class TestLLMRouting:
    def test_all_operations_have_routes(self):
        """Every LLMOperation must have a model route."""
        for op in LLMOperation:
            assert op in MODEL_ROUTING, f"Missing route for {op.value}"

    def test_refinement_agent_exists(self):
        """Refinement agent must be a defined operation."""
        assert LLMOperation.REFINEMENT_AGENT in MODEL_ROUTING

    def test_refinement_agent_uses_small(self):
        """Refinement agent must route to mistral-small-latest."""
        assert MODEL_ROUTING[LLMOperation.REFINEMENT_AGENT] == "mistral-small-latest"

    def test_small_operations_use_small(self):
        """Query extraction, response gen, and chat use Small."""
        small_ops = [
            LLMOperation.QUERY_EXTRACTION,
            LLMOperation.RESPONSE_GENERATION,
            LLMOperation.CULINARY_VALIDATION,
            LLMOperation.CHAT_FOLLOWUP,
        ]
        for op in small_ops:
            assert MODEL_ROUTING[op] == "mistral-small-latest"

    def test_large_operations_use_large(self):
        """Onboarding, remix, recreate, and narrative use Large."""
        large_ops = [
            LLMOperation.ONBOARDING_SUMMARY,
            LLMOperation.RECIPE_REMIX,
            LLMOperation.RECREATE_DISH,
            LLMOperation.FLAVOR_NARRATIVE,
        ]
        for op in large_ops:
            assert MODEL_ROUTING[op] == "mistral-large-latest"

    def test_timeout_config(self):
        """All models in the routing table must have timeout config."""
        models_used = set(MODEL_ROUTING.values())
        for model in models_used:
            assert model in TIMEOUT_SECONDS, f"No timeout for {model}"

    def test_small_timeout_is_30s(self):
        assert TIMEOUT_SECONDS["mistral-small-latest"] == 30.0

    def test_large_timeout_is_60s(self):
        assert TIMEOUT_SECONDS["mistral-large-latest"] == 60.0


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_call_llm_returns_content(self):
        """call_llm should return the model's response content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test response"
        mock_response.usage = None

        with patch("services.llm_router._get_client") as mock_client:
            mock_client.return_value.chat.complete_async = AsyncMock(return_value=mock_response)
            result = await call_llm(
                LLMOperation.QUERY_EXTRACTION,
                [{"role": "user", "content": "test"}],
            )
            assert result == "test response"

    @pytest.mark.asyncio
    async def test_call_llm_json_parses(self):
        """call_llm_json should return parsed JSON."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_response.usage = None

        with patch("services.llm_router._get_client") as mock_client:
            mock_client.return_value.chat.complete_async = AsyncMock(return_value=mock_response)
            result = await call_llm_json(
                LLMOperation.QUERY_EXTRACTION,
                [{"role": "user", "content": "test"}],
            )
            assert result == {"key": "value"}
