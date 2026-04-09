from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class FeedbackEvent(BaseModel):
    """
    A single feedback event from a user on a recipe or restaurant result.
    Used to refine the UserProfile over time via behavioral signals.
    """
    feedback_id: UUID = Field(default_factory=uuid4)
    user_id: UUID = Field(..., description="Reference to the user who submitted feedback")
    session_id: Optional[UUID] = Field(
        default=None,
        description="The session in which the feedback was given, if applicable"
    )

    # What was rated
    result_type: str = Field(
        ...,
        description="recipe | restaurant"
    )
    result_reference: str = Field(
        ...,
        description="ID or slug of the recipe or restaurant being rated"
    )

    # Feedback signal
    feedback_type: str = Field(
        ...,
        description="E.g. 'liked', 'disliked', 'saved', 'cooked', 'visited', 'skipped', 'viewed', 'shared'"
    )
    rating_value: Optional[float] = Field(
        default=None, ge=1.0, le=5.0,
        description="Optional star rating (1.0–5.0)"
    )

    # Context at feedback time
    feedback_context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Arbitrary context dict — e.g. query text, rank position, session state"
    )

    # Profile impact tracking
    profile_impact: Optional[dict[str, Any]] = Field(
        default=None,
        description="Dimensions of UserProfile updated as a result of this feedback event"
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
