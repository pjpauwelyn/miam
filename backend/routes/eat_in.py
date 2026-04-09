"""
Eat In Routes

POST /eat-in/query — Natural-language recipe discovery query.

Orchestrates session creation, pipeline execution, and message persistence.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    query: str
    session_id: str | None = None
    filters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/query", summary="Recipe discovery query")
async def eat_in_query(body: EatInQueryRequest) -> dict[str, Any]:
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
            logger.error("Failed to create session: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=f"Could not create session: {exc}",
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
        )
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline execution failed: {exc}",
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
    # 6. Assemble response
    # ------------------------------------------------------------------
    latency_ms = round((time.monotonic() - request_start) * 1000, 2)

    # Collect completed stage names from pipeline timings
    stages_completed = [
        stage
        for stage in pipeline_debug.get("stage_timings", {}).keys()
        if stage not in pipeline_debug.get("stage_errors", {})
    ]

    # Collect any warnings from retrieval context
    warnings: list[str] = pipeline_debug.get("warnings", [])

    return {
        "session_id": session_id,
        "message_id": message_id,
        "response": {
            "generated_text": generated_text,
            "results": results,
            "warnings": warnings,
        },
        "debug": {
            "latency_ms": latency_ms,
            "stages_completed": stages_completed,
            "pipeline_status": pipeline_status,
            "pipeline_debug": pipeline_debug,
        },
    }
