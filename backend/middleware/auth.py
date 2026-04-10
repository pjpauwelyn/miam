"""
Auth middleware — extracts user_id from JWT or dev fallback.

In production: requires a valid Supabase JWT in the Authorization header.
In development: falls back to user_id in the request body if no JWT is present.
If neither JWT nor body user_id exists, returns None so Pydantic validation
handles the missing field (preserving 422 behavior).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Request

from config import settings

logger = logging.getLogger(__name__)


async def get_current_user_id(request: Request) -> Optional[str]:
    """
    FastAPI dependency that resolves the current user_id.

    Priority:
    1. JWT Bearer token in Authorization header (decoded via PyJWT)
    2. (development only) user_id from the request body — only if present
    3. None — lets downstream Pydantic validation raise 422 if user_id is required
    """
    # 1. Try JWT from Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and len(auth_header) > 7:
        token = auth_header[7:]
        try:
            import jwt
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            user_id = payload.get("sub")
            if user_id:
                return user_id
        except Exception as exc:
            if settings.ENV == "production":
                logger.warning("JWT decode failed: %s", exc)
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            else:
                logger.debug("JWT decode failed in dev mode: %s", exc)

    # 2. In production, JWT is mandatory
    if settings.ENV == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authorization header required")

    # 3. Development fallback: try body user_id (only if present)
    try:
        body_bytes = await request.body()
        if body_bytes:
            import json
            body = json.loads(body_bytes)
            body_user_id = body.get("user_id")
            if body_user_id:
                logger.warning("Dev fallback: using user_id from request body (no JWT)")
                return body_user_id
    except Exception:
        pass

    # No JWT and no body user_id — return None so Pydantic raises 422
    return None
