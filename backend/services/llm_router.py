"""
LLM Router — single entry point for all Mistral AI calls.

Every LLM call in the miam backend goes through call_llm().
Model selection is driven by the LLMOperation enum — never hardcoded
in route handlers or service modules.

SDK note: uses mistralai >=1.0 (Mistral client, synchronous chat.complete(),
wrapped in run_in_executor for async compatibility).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from enum import Enum
from functools import lru_cache
from typing import Any

from mistralai import Mistral

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

# Regex to strip markdown code fences: ```json ... ``` or ``` ... ```
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that LLMs sometimes wrap JSON in."""
    raw = raw.strip()
    m = _FENCE_RE.match(raw)
    return m.group(1).strip() if m else raw


@lru_cache(maxsize=1)
def _get_client() -> Mistral:
    """Lazy singleton client (new SDK >=1.0)."""
    return Mistral(api_key=settings.MISTRAL_API_KEY)


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

    Runs synchronous chat.complete() in a thread pool so callers
    can await it without blocking the event loop.

    Args:
        operation: Which pipeline stage is calling. Determines the model.
        messages: Chat messages as plain dicts {"role": ..., "content": ...}.
        temperature: Optional override.
        max_tokens: Optional max output tokens.
        response_format: Optional response format (ignored in this SDK version).

    Returns:
        The assistant's response content as a string.
    """
    model = MODEL_ROUTING[operation]
    timeout = TIMEOUT_SECONDS.get(model, 30.0)
    client = _get_client()

    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    def _sync_call() -> str:
        response = client.chat.complete(
            model=model,
            messages=messages,
            **kwargs,
        )
        content = response.choices[0].message.content
        logger.debug(
            "LLM call completed: operation=%s model=%s",
            operation.value,
            model,
        )
        return content.strip() if content else ""

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error(
            "LLM call timed out after %.1fs: operation=%s model=%s",
            timeout, operation.value, model,
        )
        raise
    except Exception:
        logger.exception(
            "LLM call failed: operation=%s model=%s",
            operation.value, model,
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
    Convenience wrapper: calls call_llm, strips markdown fences, and parses
    the response as JSON.  Retries once with temperature=0 on parse failure.
    Returns an empty dict on second failure instead of raising, so callers
    can handle it gracefully rather than crashing.
    """
    raw = await call_llm(
        operation,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        return json.loads(_strip_fences(raw))
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

    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        logger.error(
            "JSON parse failed on retry for operation=%s — returning empty result",
            operation.value,
        )
        return {}
