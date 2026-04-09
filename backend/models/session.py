from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single turn in a session conversation."""
    message_id: UUID = Field(default_factory=uuid4)
    session_id: UUID = Field(..., description="Reference to the parent session")
    role: str = Field(
        ...,
        description="user | assistant"
    )
    content: str = Field(..., description="Raw text content of the message")
    structured: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured payload (e.g. extracted QueryOntology, result list)"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(BaseModel):
    """
    A conversation session grouping multiple queries and their results.
    Maintains mode context across the session lifecycle.
    """
    session_id: UUID = Field(default_factory=uuid4)
    user_id: UUID = Field(..., description="Reference to the authenticated user")
    mode: str = Field(
        ...,
        description="eat_in | eat_out"
    )

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None

    # Activity tracking
    query_count: int = Field(
        default=0, ge=0,
        description="Number of queries submitted in this session"
    )
