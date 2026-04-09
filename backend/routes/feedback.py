"""
Feedback Routes

Record and retrieve user feedback events for recipe and restaurant results.
Feedback signals are used to refine the UserProfile over time.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import feedback_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RecordFeedbackRequest(BaseModel):
    user_id: str = Field(..., description="UUID of the user giving feedback")
    result_type: str = Field(..., description="'recipe' or 'restaurant'")
    result_reference: str = Field(
        ..., description="ID or slug of the recipe/restaurant being rated"
    )
    feedback_type: str = Field(
        ...,
        description=(
            "Signal type: 'liked', 'disliked', 'saved', 'cooked', "
            "'visited', 'skipped', 'viewed', 'shared'"
        ),
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session UUID in which feedback was given",
    )
    rating_value: float | None = Field(
        default=None,
        ge=1.0,
        le=5.0,
        description="Optional star rating (1.0–5.0)",
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional context dict (e.g. query text, rank position, session state)",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", summary="Record a feedback event")
async def record_feedback(body: RecordFeedbackRequest) -> dict[str, Any]:
    """
    Records a feedback event (like, dislike, save, cook, skip, etc.) for a
    recipe or restaurant result.

    Feedback events power the behavioral signal loop used to refine
    the user's personal profile over time.
    """
    try:
        row = await feedback_service.record_feedback(
            user_id=body.user_id,
            feedback_type=body.feedback_type,
            result_type=body.result_type,
            result_reference=body.result_reference,
            session_id=body.session_id,
            rating_value=body.rating_value,
            context=body.context,
        )
        logger.info(
            "Feedback recorded: user_id=%s type=%s ref=%s",
            body.user_id,
            body.feedback_type,
            body.result_reference,
        )
        return {"status": "recorded", "feedback": row}
    except Exception as exc:
        logger.error(
            "Failed to record feedback for user_id=%s: %s", body.user_id, exc
        )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to record feedback: {exc}",
        )


@router.get("/user/{user_id}", summary="Get user feedback history")
async def get_user_feedback(
    user_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Returns the user's most recent feedback events, ordered newest-first.

    Query parameters:
        limit: Maximum number of records to return (default 50, max 200).
    """
    try:
        events = await feedback_service.get_user_feedback(
            user_id=user_id,
            limit=max(1, min(limit, 200)),  # clamp between 1 and 200
        )
        return {
            "user_id": user_id,
            "feedback_count": len(events),
            "feedback_events": events,
        }
    except Exception as exc:
        logger.error(
            "Failed to retrieve feedback for user_id=%s: %s", user_id, exc
        )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to retrieve feedback: {exc}",
        )
