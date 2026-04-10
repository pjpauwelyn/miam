"""
Session Manager Service

Manages session lifecycle and message storage via Supabase REST API.
All database interactions use httpx (no direct PostgreSQL connection).
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


# ---------------------------------------------------------------------------
# Session operations
# ---------------------------------------------------------------------------


async def create_session(user_id: str, mode: str = "eat_in") -> dict:
    """
    Creates a new session in Supabase.

    Returns:
        dict with keys: session_id, user_id, mode, started_at
    """
    session_id = str(uuid4())
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
        "query_count": 0,
    }

    url = f"{SUPABASE_REST_BASE}/sessions"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=_rest_headers(), json=payload)

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to create session for user_id=%s: %s %s",
                user_id,
                resp.status_code,
                resp.text[:300],
            )
            raise RuntimeError(
                f"Supabase session creation failed: {resp.status_code} {resp.text[:200]}"
            )

        rows = resp.json()
        row = rows[0] if isinstance(rows, list) else rows
        logger.debug("Created session session_id=%s for user_id=%s", session_id, user_id)
        return {
            "session_id": row.get("session_id", session_id),
            "user_id": row.get("user_id", user_id),
            "mode": row.get("mode", mode),
            "started_at": row.get("started_at"),
        }

    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Exception creating session for user_id=%s: %s", user_id, exc)
        raise RuntimeError(f"Session creation error: {exc}") from exc


async def add_message(
    session_id: str,
    role: str,
    content: str,
    structured: dict | None = None,
) -> dict:
    """
    Adds a message to the given session.

    Args:
        session_id: UUID string of the session.
        role: "user" or "assistant".
        content: Raw text content.
        structured: Optional structured payload (e.g. results, query ontology).

    Returns:
        dict with the inserted message row.
    """
    message_id = str(uuid4())
    payload: dict[str, Any] = {
        "message_id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
    }
    if structured is not None:
        payload["structured"] = structured

    url = f"{SUPABASE_REST_BASE}/messages"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=_rest_headers(), json=payload)

        if resp.status_code not in (200, 201):
            logger.error(
                "Failed to add message session_id=%s role=%s: %s %s",
                session_id,
                role,
                resp.status_code,
                resp.text[:300],
            )
            raise RuntimeError(
                f"Supabase message insert failed: {resp.status_code} {resp.text[:200]}"
            )

        rows = resp.json()
        row = rows[0] if isinstance(rows, list) else rows
        logger.debug(
            "Added message message_id=%s to session_id=%s (role=%s)",
            message_id,
            session_id,
            role,
        )
        return row

    except RuntimeError:
        raise
    except Exception as exc:
        logger.error(
            "Exception adding message to session_id=%s: %s", session_id, exc
        )
        raise RuntimeError(f"Message insert error: {exc}") from exc


async def get_session_history(session_id: str, limit: int = 10) -> list[dict]:
    """
    Retrieves the most recent messages for a session, ordered oldest-first.

    Args:
        session_id: UUID string of the session.
        limit: Maximum number of messages to return (default 10).

    Returns:
        List of message dicts ordered by created_at ascending.
    """
    url = (
        f"{SUPABASE_REST_BASE}/messages"
        f"?session_id=eq.{quote(str(session_id), safe='')}"
        f"&order=created_at.asc"
        f"&limit={limit}"
        f"&select=message_id,session_id,role,content,structured,created_at"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_rest_headers())

        if resp.status_code != 200:
            logger.error(
                "Failed to fetch history for session_id=%s: %s %s",
                session_id,
                resp.status_code,
                resp.text[:300],
            )
            return []

        rows = resp.json()
        logger.debug(
            "Fetched %d messages for session_id=%s", len(rows), session_id
        )
        return rows

    except Exception as exc:
        logger.error(
            "Exception fetching history for session_id=%s: %s", session_id, exc
        )
        return []


async def increment_query_count(session_id: str) -> None:
    """
    Increments the query_count for the given session using a Supabase RPC
    or a read-then-write approach.

    Uses a read-then-increment pattern since Supabase REST does not expose
    native atomic increment without a custom RPC.
    """
    # Fetch current count
    get_url = (
        f"{SUPABASE_REST_BASE}/sessions"
        f"?session_id=eq.{quote(str(session_id), safe='')}"
        f"&select=query_count"
        f"&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            get_resp = await client.get(get_url, headers=_rest_headers())

            if get_resp.status_code != 200 or not get_resp.json():
                logger.warning(
                    "Could not fetch query_count for session_id=%s: %s",
                    session_id,
                    get_resp.status_code,
                )
                return

            rows = get_resp.json()
            current_count: int = rows[0].get("query_count", 0) or 0
            new_count = current_count + 1

            patch_url = (
                f"{SUPABASE_REST_BASE}/sessions"
                f"?session_id=eq.{quote(str(session_id), safe='')}"
            )
            patch_headers = {**_rest_headers(), "Prefer": "return=minimal"}
            patch_resp = await client.patch(
                patch_url,
                headers=patch_headers,
                json={"query_count": new_count},
            )

        if patch_resp.status_code not in (200, 204):
            logger.warning(
                "Failed to increment query_count for session_id=%s: %s %s",
                session_id,
                patch_resp.status_code,
                patch_resp.text[:200],
            )
        else:
            logger.debug(
                "Incremented query_count to %d for session_id=%s",
                new_count,
                session_id,
            )

    except Exception as exc:
        logger.error(
            "Exception incrementing query_count for session_id=%s: %s",
            session_id,
            exc,
        )


async def end_session(session_id: str) -> None:
    """
    Sets ended_at to the current UTC timestamp for the given session.
    """
    from datetime import datetime, timezone

    ended_at = datetime.now(timezone.utc).isoformat()

    patch_url = (
        f"{SUPABASE_REST_BASE}/sessions"
        f"?session_id=eq.{quote(str(session_id), safe='')}"
    )
    patch_headers = {**_rest_headers(), "Prefer": "return=minimal"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.patch(
                patch_url,
                headers=patch_headers,
                json={"ended_at": ended_at},
            )

        if resp.status_code not in (200, 204):
            logger.warning(
                "Failed to end session_id=%s: %s %s",
                session_id,
                resp.status_code,
                resp.text[:200],
            )
        else:
            logger.debug("Ended session_id=%s at %s", session_id, ended_at)

    except Exception as exc:
        logger.error("Exception ending session_id=%s: %s", session_id, exc)


async def get_session(session_id: str) -> dict | None:
    """
    Fetches a single session record by session_id.

    Returns:
        Session dict or None if not found.
    """
    url = (
        f"{SUPABASE_REST_BASE}/sessions"
        f"?session_id=eq.{quote(str(session_id), safe='')}"
        f"&select=session_id,user_id,mode,started_at,ended_at,query_count"
        f"&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_rest_headers())

        if resp.status_code != 200:
            logger.error(
                "Failed to fetch session_id=%s: %s %s",
                session_id,
                resp.status_code,
                resp.text[:300],
            )
            return None

        rows = resp.json()
        if not rows:
            return None

        return rows[0]

    except Exception as exc:
        logger.error("Exception fetching session_id=%s: %s", session_id, exc)
        return None
