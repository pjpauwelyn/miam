"""
Database connection layer.

Supports two modes:
1. Direct asyncpg connection (production, Docker local dev)
2. Supabase REST API fallback (when direct PG is unavailable)

The REST API mode is used during development when the sandbox
can't reach the Supabase PostgreSQL port directly.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote
from uuid import UUID

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Global connection pool (for direct asyncpg mode)
_pool = None


class SupabaseREST:
    """
    Lightweight wrapper around Supabase REST API for database operations.
    Used when direct PostgreSQL connections are not available.
    """

    def __init__(self):
        self.base_url = f"{settings.SUPABASE_URL}/rest/v1"
        self.headers = settings.supabase_rest_headers

    async def insert(self, table: str, data: dict | list[dict]) -> list[dict]:
        """Insert one or more rows into a table."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/{table}",
                headers=self.headers,
                json=data if isinstance(data, list) else [data] if isinstance(data, dict) else data,
                timeout=30.0,
            )
            if resp.status_code not in (200, 201):
                logger.error("Supabase insert failed: %s %s", resp.status_code, resp.text)
                raise Exception(f"Supabase insert error: {resp.status_code} {resp.text}")
            return resp.json()

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict]:
        """Select rows from a table with optional filters."""
        params = {"select": columns}
        if limit:
            params["limit"] = str(limit)
        if order:
            params["order"] = order

        headers = {**self.headers}

        # Build filter query params
        filter_params = ""
        if filters:
            for key, value in filters.items():
                filter_params += f"&{key}=eq.{quote(str(value), safe='')}"

        url = f"{self.base_url}/{table}?select={columns}{filter_params}"
        if limit:
            url += f"&limit={limit}"
        if order:
            url += f"&order={order}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30.0)
            if resp.status_code != 200:
                logger.error("Supabase select failed: %s %s", resp.status_code, resp.text)
                raise Exception(f"Supabase select error: {resp.status_code} {resp.text}")
            return resp.json()

    async def update(
        self, table: str, data: dict, filters: dict[str, Any]
    ) -> list[dict]:
        """Update rows matching filters."""
        filter_params = "&".join(f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items())
        url = f"{self.base_url}/{table}?{filter_params}"

        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                url, headers=self.headers, json=data, timeout=30.0,
            )
            if resp.status_code not in (200, 204):
                logger.error("Supabase update failed: %s %s", resp.status_code, resp.text)
                raise Exception(f"Supabase update error: {resp.status_code} {resp.text}")
            return resp.json() if resp.status_code == 200 else []

    async def delete(self, table: str, filters: dict[str, Any]) -> None:
        """Delete rows matching filters."""
        filter_params = "&".join(f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items())
        url = f"{self.base_url}/{table}?{filter_params}"

        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=self.headers, timeout=30.0)
            if resp.status_code not in (200, 204):
                logger.error("Supabase delete failed: %s %s", resp.status_code, resp.text)
                raise Exception(f"Supabase delete error: {resp.status_code} {resp.text}")

    async def rpc(self, function_name: str, params: dict | None = None) -> Any:
        """Call a Supabase RPC (stored function)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/rpc/{function_name}",
                headers=self.headers,
                json=params or {},
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.error("Supabase RPC failed: %s %s", resp.status_code, resp.text)
                raise Exception(f"Supabase RPC error: {resp.status_code} {resp.text}")
            return resp.json()

    async def count(self, table: str, filters: dict[str, Any] | None = None) -> int:
        """Get row count for a table."""
        headers = {**self.headers, "Prefer": "count=exact"}
        filter_params = ""
        if filters:
            filter_params = "&".join(f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items())

        url = f"{self.base_url}/{table}?select=count"
        if filter_params:
            url += f"&{filter_params}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30.0)
            if resp.status_code != 200:
                return 0
            # Count is in the content-range header or body
            data = resp.json()
            if data and isinstance(data, list) and data[0].get("count") is not None:
                return data[0]["count"]
            return len(data) if data else 0


# Singleton REST client
_rest_client: Optional[SupabaseREST] = None


def get_rest_client() -> SupabaseREST:
    """Get or create the Supabase REST client singleton."""
    global _rest_client
    if _rest_client is None:
        _rest_client = SupabaseREST()
    return _rest_client


async def get_pool():
    """
    Get the asyncpg connection pool.
    Falls back to REST client if direct PG is unavailable.
    """
    global _pool
    if _pool is not None:
        return _pool

    if settings.DATABASE_URL:
        try:
            import asyncpg
            _pool = await asyncpg.create_pool(
                settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
                min_size=2,
                max_size=10,
            )
            logger.info("Connected to PostgreSQL via asyncpg")
            return _pool
        except Exception as e:
            logger.warning("Direct PG connection failed (%s), using REST API", e)

    # Return REST client as fallback
    return get_rest_client()


async def close_pool():
    """Close the connection pool if active."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
