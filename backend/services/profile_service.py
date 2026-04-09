"""
Profile service — CRUD + ontology fusion logic.

Handles the persistent PersonalOntology and the fusion with
ephemeral QueryOntology to produce the FusedOntology/RetrievalContext
that drives retrieval, ranking, refinement, and generation.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from models.personal_ontology import UserProfile, PreferenceLevel
from models.query_ontology import QueryOntology, QueryMode
from models.fused_ontology import RetrievalContext

logger = logging.getLogger(__name__)


async def get_profile(pool, user_id: UUID) -> Optional[dict]:
    """Fetch a user profile from the database."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, profile_status, profile_data, created_at, updated_at "
            "FROM user_profiles WHERE user_id = $1",
            user_id,
        )
    if row is None:
        return None
    return {
        "user_id": str(row["user_id"]),
        "profile_status": row["profile_status"],
        "profile_data": row["profile_data"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def create_profile(pool, user_id: UUID, profile_data: dict) -> dict:
    """Create a new user profile."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_profiles (user_id, profile_status, profile_data)
               VALUES ($1, $2, $3)""",
            user_id,
            "incomplete",
            json.dumps(profile_data),
        )
    return {"user_id": str(user_id), "status": "created"}


async def update_profile(pool, user_id: UUID, profile_data: dict) -> dict:
    """Update an existing user profile."""
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE user_profiles
               SET profile_data = $2, updated_at = NOW()
               WHERE user_id = $1""",
            user_id,
            json.dumps(profile_data),
        )
    return {"user_id": str(user_id), "status": "updated"}


async def delete_profile(pool, user_id: UUID) -> dict:
    """
    GDPR cascade delete — removes all user data.
    Order matters due to foreign key constraints.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete in dependency order
            await conn.execute(
                "DELETE FROM activity_events WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM social_follows WHERE follower_id = $1 OR followed_id = $1",
                user_id,
            )
            await conn.execute(
                "DELETE FROM user_saved_restaurants WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM user_saved_recipes WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM feedback_events WHERE user_id = $1", user_id
            )
            # Delete messages via sessions
            await conn.execute(
                """DELETE FROM messages WHERE session_id IN
                   (SELECT session_id FROM sessions WHERE user_id = $1)""",
                user_id,
            )
            await conn.execute(
                "DELETE FROM sessions WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM user_profiles WHERE user_id = $1", user_id
            )
    return {"user_id": str(user_id), "status": "deleted"}


async def export_profile(pool, user_id: UUID) -> dict:
    """
    GDPR data export — returns full profile + session history.
    """
    profile = await get_profile(pool, user_id)
    if profile is None:
        return {"error": "Profile not found"}

    async with pool.acquire() as conn:
        sessions = await conn.fetch(
            "SELECT * FROM sessions WHERE user_id = $1 ORDER BY started_at",
            user_id,
        )
        feedback = await conn.fetch(
            "SELECT * FROM feedback_events WHERE user_id = $1 ORDER BY created_at",
            user_id,
        )
        saved_recipes = await conn.fetch(
            "SELECT * FROM user_saved_recipes WHERE user_id = $1",
            user_id,
        )
        saved_restaurants = await conn.fetch(
            "SELECT * FROM user_saved_restaurants WHERE user_id = $1",
            user_id,
        )

    # Fetch messages for each session
    session_data = []
    for s in sessions:
        async with pool.acquire() as conn:
            messages = await conn.fetch(
                "SELECT * FROM messages WHERE session_id = $1 ORDER BY created_at",
                s["session_id"],
            )
        session_data.append({
            "session_id": str(s["session_id"]),
            "mode": s["mode"],
            "started_at": s["started_at"].isoformat(),
            "query_count": s["query_count"],
            "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m["created_at"].isoformat(),
                }
                for m in messages
            ],
        })

    return {
        "profile": profile,
        "sessions": session_data,
        "feedback_events": [dict(f) for f in feedback],
        "saved_recipes": [str(r["recipe_id"]) for r in saved_recipes],
        "saved_restaurants": [r["fsq_id"] for r in saved_restaurants],
    }


def fuse_ontologies(
    personal: UserProfile,
    query: QueryOntology,
) -> RetrievalContext:
    """
    Fuse the persistent PersonalOntology with the ephemeral QueryOntology
    to produce a RetrievalContext that drives the retrieval stage.

    Fusion rules:
    - Query-explicit values always override profile defaults
    - Dietary hard stops are NEVER overridden (profile always wins for safety)
    - Soft preferences blend: query weight 0.7, profile weight 0.3
    - Conflicts are surfaced in the warnings list
    """
    hard_filters: dict[str, Any] = {}
    soft_filters: dict[str, Any] = {}
    scoring_vector: dict[str, float] = {}
    warnings: list[str] = []

    # --- Hard filters (non-negotiable) ---

    # Dietary restrictions from profile — always enforced
    for restriction in personal.dietary.restrictions:
        hard_filters[f"dietary_{restriction.name}"] = restriction.is_strict

    # Allergy-based exclusions
    for allergen in personal.dietary.allergens:
        hard_filters[f"exclude_allergen_{allergen}"] = True

    # --- Mode-specific handling ---
    if query.mode == QueryMode.EAT_IN:
        eat_in = query.eat_in_attributes
        if eat_in:
            # Time constraint
            if eat_in.time_budget_min:
                hard_filters["max_time_min"] = eat_in.time_budget_min

            # Pantry ingredients
            if eat_in.pantry_items:
                soft_filters["prefer_ingredients"] = eat_in.pantry_items

            # Skill level from profile
            soft_filters["max_difficulty"] = personal.cooking.skill.value

            # Equipment from profile
            if personal.cooking.equipment:
                soft_filters["available_equipment"] = [
                    e.name for e in personal.cooking.equipment
                ]

    elif query.mode == QueryMode.EAT_OUT:
        eat_out = query.eat_out_attributes
        if eat_out:
            # Location
            if eat_out.location_text:
                soft_filters["location"] = eat_out.location_text

            # Budget
            if eat_out.budget_constraint:
                hard_filters["max_price"] = eat_out.budget_constraint

            # Party size
            if eat_out.party_size:
                soft_filters["party_size"] = eat_out.party_size

            # Vibe
            if eat_out.vibe_keywords:
                soft_filters["vibes"] = eat_out.vibe_keywords

    # --- Scoring vector (cuisine affinities) ---
    for affinity in personal.cuisine.affinities:
        scoring_vector[affinity.cuisine_name] = affinity.affinity_score

    # --- Query cuisine preferences override/boost ---
    if query.attributes:
        for attr in query.attributes:
            if attr.dimension == "cuisine" and attr.value:
                scoring_vector[str(attr.value)] = 1.0  # Max boost for explicit query

    # --- Conflict detection ---
    if query.conflicts:
        for conflict in query.conflicts:
            warnings.append(
                f"Conflict detected: {conflict.description} "
                f"(resolution: {conflict.resolution.value})"
            )

    # Profile tensions
    for tension in personal.tensions:
        warnings.append(f"Profile tension: {tension.description}")

    return RetrievalContext(
        hard_filters=hard_filters,
        soft_filters=soft_filters,
        scoring_vector=scoring_vector,
        warnings=warnings,
    )
