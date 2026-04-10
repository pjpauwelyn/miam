"""
Sessions Routes

Manage session lifecycle: creation, retrieval, message history, and termination.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    user_id: str
    mode: str = "eat_in"  # "eat_in" | "eat_out"
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", summary="Create a new session")
async def create_session(body: CreateSessionRequest) -> dict[str, Any]:
    """
    Creates a new recommendation session and returns its ID.
    Sessions maintain conversation context across multiple queries.
    """
    try:
        session = await session_manager.create_session(
            user_id=body.user_id,
            mode=body.mode,
        )
        logger.info(
            "Session created: session_id=%s user_id=%s mode=%s",
            session.get("session_id"),
            body.user_id,
            body.mode,
        )
        return session
    except Exception as exc:
        logger.error("Failed to create session for user_id=%s: %s", body.user_id, exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Could not create session. Please try again.")


@router.get("/{session_id}", summary="Get session details")
async def get_session(session_id: str) -> dict[str, Any]:
    """
    Returns the full session record (metadata, timing, query count) for the given session ID.
    """
    session = await session_manager.get_session(session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    return session


@router.get("/{session_id}/messages", summary="Get session message history")
async def get_session_messages(
    session_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Returns the message history for the given session, ordered oldest-first.

    Query parameters:
        limit: Maximum number of messages to return (default 10, max recommended 50).
    """
    # Verify session exists first
    session = await session_manager.get_session(session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )

    messages = await session_manager.get_session_history(
        session_id=session_id,
        limit=max(1, min(limit, 100)),  # clamp between 1 and 100
    )
    return {
        "session_id": session_id,
        "message_count": len(messages),
        "messages": messages,
    }


@router.post("/{session_id}/end", summary="End a session")
async def end_session(session_id: str) -> dict[str, Any]:
    """
    Marks a session as ended by setting its ended_at timestamp.
    Subsequent calls are idempotent — the session will simply remain ended.
    """
    # Verify session exists first
    session = await session_manager.get_session(session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )

    try:
        await session_manager.end_session(session_id=session_id)
        logger.info("Session ended: session_id=%s", session_id)
        return {"session_id": session_id, "status": "ended"}
    except Exception as exc:
        logger.error("Failed to end session_id=%s: %s", session_id, exc, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Could not end session. Please try again.",
        )
