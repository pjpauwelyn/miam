"""
LLM Router — single entry point for all Mistral AI calls.

Every LLM call in the miam backend goes through call_llm().
Model selection is driven by the LLMOperation enum — never hardcoded
in route handlers or service modules.

SDK note: uses mistralai <1.0 (MistralClient, sync chat.complete).
"""
from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from functools import lru_cache
from typing import Any

from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

from config import settings

logger = logging.getLogger(__name__)


class LLMOperation(str, Enum):
    """All LLM-backed operations in the miam pipeline."""
    QUERY_EXTRACTION = "query_extraction"
    REFINEMENT_AGENT = "refinement_agent"
    RESPONSE_GENERATION = "response_generation"
    ONBOARDING_SUMMARY = "onboarding_summary"
    RECIPE_REMIX = "recipe_remix"
    RECREATE_DISH = "recreate_dish"
    FLAVOR_NARRATIVE = "flavor_narrative"
    CULINARY_VALIDATION = "culinary_validation"
    CHAT_FOLLOWUP = "chat_followup"
    CUISINE_CLASSIFICATION = "cuisine_classification"
    RECIPE_ENRICHMENT = "recipe_enrichment"


# Non-negotiable routing table — from miam_master_plan_v2 §2
MODEL_ROUTING: dict[LLMOperation, str] = {
    LLMOperation.QUERY_EXTRACTION: "mistral-small-latest",
    LLMOperation.REFINEMENT_AGENT: "mistral-small-latest",
    LLMOperation.RESPONSE_GENERATION: "mistral-small-latest",
    LLMOperation.ONBOARDING_SUMMARY: "mistral-large-latest",
    LLMOperation.RECIPE_REMIX: "mistral-large-latest",
    LLMOperation.RECREATE_DISH: "mistral-large-latest",
    LLMOperation.FLAVOR_NARRATIVE: "mistral-large-latest",
    LLMOperation.CULINARY_VALIDATION: "mistral-small-latest",
    LLMOperation.CHAT_FOLLOWUP: "mistral-small-latest",
    LLMOperation.CUISINE_CLASSIFICATION: "mistral-small-latest",
    LLMOperation.RECIPE_ENRICHMENT: "mistral-small-latest",
}

# Timeout configuration per model tier (seconds)
TIMEOUT_SECONDS: dict[str, float] = {
    "mistral-small-latest": 30.0,
    "mistral-large-latest": 60.0,
}


@lru_cache(maxsize=1)
def _get_client() -> MistralClient:
    """Lazy singleton client (old SDK)."""
    return MistralClient(api_key=settings.MISTRAL_API_KEY)


def _to_chat_messages(messages: list[dict[str, str]]) -> list[ChatMessage]:
    """Convert plain dicts to ChatMessage objects required by old SDK."""
    return [ChatMessage(role=m["role"], content=m["content"]) for m in messages]


async def call_llm(
    operation: LLMOperation,
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> str:
    """
    Central LLM call function. All Mistral API calls go through here.

    Runs the synchronous MistralClient call in a thread pool so callers
    can await it without blocking the event loop.

    Args:
        operation: Which pipeline stage is calling. Determines the model.
        messages: Chat messages in OpenAI-compatible format.
        temperature: Optional override.
        max_tokens: Optional max output tokens.
        response_format: Ignored for old SDK (kept for API compatibility).

    Returns:
        The assistant's response content as a string.

    Raises:
        asyncio.TimeoutError: If the call exceeds the configured timeout.
        Exception: Any Mistral SDK error is logged and re-raised.
    """
    model = MODEL_ROUTING[operation]
    timeout = TIMEOUT_SECONDS.get(model, 30.0)
    client = _get_client()
    chat_messages = _to_chat_messages(messages)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": chat_messages,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    loop = asyncio.get_event_loop()

    def _sync_call() -> str:
        response = client.chat(
            model=kwargs["model"],
            messages=kwargs["messages"],
            **{k: v for k, v in kwargs.items() if k not in ("model", "messages")},
        )
        content = response.choices[0].message.content
        logger.debug(
            "LLM call completed: operation=%s model=%s",
            operation.value,
            model,
        )
        return content.strip() if content else ""

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error(
            "LLM call timed out after %.1fs: operation=%s model=%s",
            timeout,
            operation.value,
            model,
        )
        raise
    except Exception:
        logger.exception(
            "LLM call failed: operation=%s model=%s",
            operation.value,
            model,
        )
        raise


async def call_llm_json(
    operation: LLMOperation,
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict | list:
    """
    Convenience wrapper: calls call_llm and parses the response as JSON.
    Retries once with temperature=0 on parse failure.
    """
    raw = await call_llm(
        operation,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "JSON parse failed for operation=%s, retrying with temperature=0",
            operation.value,
        )
        raw = await call_llm(
            operation,
            messages,
            temperature=0,
            max_tokens=max_tokens,
        )
        return json.loads(raw)
