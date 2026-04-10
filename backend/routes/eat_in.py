"""
Eat In Routes

POST /eat-in/query — Natural-language recipe discovery query.

Orchestrates session creation, pipeline execution, and message persistence.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from config import settings
from middleware.auth import get_current_user_id
from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
from services.session_manager import (
    add_message,
    create_session,
    increment_query_count,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class EatInQueryRequest(BaseModel):
    user_id: str
    query: str = Field(..., max_length=5000)
    session_id: str | None = None
    filters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/query", summary="Recipe discovery query")
async def eat_in_query(body: EatInQueryRequest, auth_user_id: Optional[str] = Depends(get_current_user_id)) -> dict[str, Any]:
    """
    Processes a natural-language query for recipe recommendations.

    Pipeline stages (handled by run_eat_in_pipeline):
      0. Load user profile
      1+2. Extract QueryOntology via LLM
      2b. Fuse with PersonalOntology → RetrievalContext
      3. Retrieve matching recipes via vector search + metadata filters
      4. Rank candidates
      5. Refine results (quality gate)
      6. Generate response

    Session is created automatically if session_id is not provided.
    User and assistant messages are persisted to Supabase.
    """
    request_start = time.monotonic()

    # Use JWT-derived user_id when available, otherwise keep body value
    if auth_user_id:
        body.user_id = auth_user_id

    # ------------------------------------------------------------------
    # 1. Resolve or create session
    # ------------------------------------------------------------------
    session_id = body.session_id
    if not session_id:
        try:
            session_data = await create_session(
                user_id=body.user_id, mode="eat_in"
            )
            session_id = session_data["session_id"]
            logger.info(
                "Created new session session_id=%s for user_id=%s",
                session_id,
                body.user_id,
            )
        except Exception as exc:
            logger.error("Failed to create session: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Could not create session. Please try again.",
            )

    # ------------------------------------------------------------------
    # 2. Persist user message
    # ------------------------------------------------------------------
    try:
        await add_message(
            session_id=session_id,
            role="user",
            content=body.query,
        )
    except Exception as exc:
        # Non-fatal: log and continue
        logger.warning(
            "Failed to persist user message for session_id=%s: %s",
            session_id,
            exc,
        )

    # ------------------------------------------------------------------
    # 3. Run the pipeline
    # ------------------------------------------------------------------
    try:
        pipeline_result = await run_eat_in_pipeline(
            raw_query=body.query,
            user_id=body.user_id,
            session_id=session_id,
        )
    except Exception as exc:
        logger.error(
            "Pipeline error for user_id=%s session_id=%s: %s",
            body.user_id,
            session_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Pipeline execution failed. Please try again.",
        )

    generated_text: str = pipeline_result.get("generated_text", "")
    results: list = pipeline_result.get("results", [])
    pipeline_debug: dict = pipeline_result.get("debug", {})
    pipeline_status: str = pipeline_result.get("pipeline_status", "ok")

    # ------------------------------------------------------------------
    # 4. Persist assistant message
    # ------------------------------------------------------------------
    message_id: str = ""
    try:
        structured_payload = {
            "pipeline_status": pipeline_status,
            "results": results,
        }
        msg_row = await add_message(
            session_id=session_id,
            role="assistant",
            content=generated_text,
            structured=structured_payload,
        )
        message_id = msg_row.get("message_id", "")
    except Exception as exc:
        logger.warning(
            "Failed to persist assistant message for session_id=%s: %s",
            session_id,
            exc,
        )

    # ------------------------------------------------------------------
    # 5. Increment query count (non-fatal)
    # ------------------------------------------------------------------
    try:
        await increment_query_count(session_id=session_id)
    except Exception as exc:
        logger.warning(
            "Failed to increment query count for session_id=%s: %s",
            session_id,
            exc,
        )

    # ------------------------------------------------------------------
    # 6. Build response
    # ------------------------------------------------------------------
    elapsed_ms = round((time.monotonic() - request_start) * 1000)

    response_data: dict[str, Any] = {
        "session_id": session_id,
        "message_id": message_id,
        "generated_text": generated_text,
        "results": results,
        "pipeline_status": pipeline_status,
        "elapsed_ms": elapsed_ms,
    }

    if settings.ENV == "development":
        response_data["debug"] = {
            "stages": pipeline_debug.get("stages", []),
            "timing": pipeline_debug.get("timing", {}),
        }

    return response_data
