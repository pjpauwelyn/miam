"""
Feedback Service

Records and retrieves user feedback events via Supabase REST API.
Feedback events are used to refine the UserProfile over time via behavioral signals.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from config import settings

logger = logging.getLogger(__name__)

SUPABASE_REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"


def _rest_headers() -> dict[str, str]:
    return settings.supabase_rest_headers


async def record_feedback(
    user_id: str,
    feedback_type: str,
    result_type: str,
    result_reference: str,
    session_id: str | None = None,
    rating_value: float | None = None,
    context: dict | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """
    Records a feedback event for a recipe or restaurant result.

    Args:
        user_id: UUID string of the user giving feedback.
        feedback_type: Signal type — e.g. 'liked', 'disliked', 'saved', 'cooked',
                       'visited', 'skipped', 'viewed', 'shared'.
        result_type: 'recipe' or 'restaurant'.
        result_reference: ID or slug of the item being rated.
        session_id: Optional UUID of the session in which feedback was given.
        rating_value: Optional star rating (1.0–5.0).
        context: Optional context dict (e.g. query text, rank position).

    Returns:
        dict with the inserted feedback_event row.
    """
    feedback_id = str(uuid4())
    payload: dict[str, Any] = {
        "feedback_id": feedback_id,
        "user_id": user_id,
        "result_type": result_type,
        "result_reference": result_reference,
        "feedback_type": feedback_type,
    }

    if session_id is not None:
        payload["session_id"] = session_id
    if rating_value is not None:
        payload["rating_value"] = rating_value
    if context is not None:
        payload["feedback_context"] = context

    url = f"{SUPABASE_REST_BASE}/feedback_events"
    _client = client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await _client.post(url, headers=_rest_headers(), json=payload)

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to record feedback for user_id=%s: %s %s",
                user_id,
                resp.status_code,
                resp.text[:300],
            )
            raise RuntimeError(
                f"Supabase feedback insert failed: {resp.status_code} {resp.text[:200]}"
            )

        rows = resp.json()
        row = rows[0] if isinstance(rows, list) else rows
        logger.debug(
            "Recorded feedback feedback_id=%s user_id=%s type=%s ref=%s",
            feedback_id,
            user_id,
            feedback_type,
            result_reference,
        )
        return row

    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Exception recording feedback for user_id=%s: %s", user_id, exc)
        raise RuntimeError(f"Feedback record error: {exc}") from exc
    finally:
        if not client:
            await _client.aclose()


async def get_user_feedback(user_id: str, limit: int = 50) -> list[dict]:
    """
    Retrieves the most recent feedback events for a user.

    Args:
        user_id: UUID string of the user.
        limit: Maximum number of records to return (default 50).

    Returns:
        List of feedback_event dicts ordered by created_at descending.
    """
    url = (
        f"{SUPABASE_REST_BASE}/feedback_events"
        f"?user_id=eq.{quote(str(user_id), safe='')}"
        f"&order=created_at.desc"
        f"&limit={limit}"
        f"&select=feedback_id,user_id,session_id,result_type,result_reference,"
        f"feedback_type,rating_value,feedback_context,profile_impact,created_at"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_rest_headers())

        if resp.status_code != 200:
            logger.error(
                "Failed to fetch feedback for user_id=%s: %s %s",
                user_id,
                resp.status_code,
                resp.text[:300],
            )
            return []

        rows = resp.json()
        logger.debug(
            "Fetched %d feedback events for user_id=%s", len(rows), user_id
        )
        return rows

    except Exception as exc:
        logger.error(
            "Exception fetching feedback for user_id=%s: %s", user_id, exc
        )
        return []
