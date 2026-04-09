"""
Eat In Pipeline Orchestrator

Coordinates all 6 pipeline stages for a single eat-in query.

Function signature:
    async def run_eat_in_pipeline(
        raw_query: str,
        user_id: str,
        session_id: str | None = None,
    ) -> dict

Returns a complete response dict with generated_text, results, and debug info.
Each stage has graceful degradation — a failure at one stage does not
necessarily abort the pipeline; it returns a partial result with an error flag.
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any
from uuid import UUID

import httpx

from config import settings
from models.personal_ontology import UserProfile
from models.query_ontology import QueryMode, QueryOntology, EatInAttributes
from services.pipeline.fusion import fuse_ontologies
from services.pipeline.query_extractor import extract_query
from services.pipeline.ranker import rank_recipes
from services.pipeline.refinement_agent import refine_results
from services.pipeline.response_generator import generate_response
from services.pipeline.retriever import retrieve_recipes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase REST: profile loader
# ---------------------------------------------------------------------------

SUPABASE_REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"


def _rest_headers() -> dict[str, str]:
    return settings.supabase_rest_headers


async def _load_profile_from_supabase(user_id: str) -> UserProfile | None:
    """
    Load a UserProfile from the user_profiles table via Supabase REST API.

    Returns None if the profile is not found or cannot be parsed.
    """
    url = (
        f"{SUPABASE_REST_BASE}/user_profiles"
        f"?user_id=eq.{user_id}"
        f"&select=user_id,profile_status,profile_data"
        f"&limit=1"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=_rest_headers())

        if resp.status_code != 200:
            logger.error(
                "Failed to fetch profile for user_id=%s: %s %s",
                user_id,
                resp.status_code,
                resp.text[:200],
            )
            return None

        rows = resp.json()
        if not rows:
            logger.warning("No profile found for user_id=%s", user_id)
            return None

        row = rows[0]
        profile_data = row.get("profile_data") or {}

        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
            except json.JSONDecodeError:
                logger.error("Failed to parse profile_data JSON for user_id=%s", user_id)
                return None

        # Ensure user_id is set in profile_data
        if "user_id" not in profile_data:
            profile_data["user_id"] = user_id

        profile = UserProfile(**profile_data)
        logger.debug("Loaded profile for user_id=%s (status=%s)", user_id, row.get("profile_status"))
        return profile

    except Exception as exc:
        logger.error("Exception loading profile for user_id=%s: %s", user_id, exc)
        return None


def _build_default_profile(user_id: str) -> UserProfile:
    """
    Build a minimal default UserProfile when no profile is found.
    This allows the pipeline to run with sensible defaults.
    """
    return UserProfile(user_id=UUID(user_id))


# ---------------------------------------------------------------------------
# Query text enrichment for embedding
# ---------------------------------------------------------------------------

def _enrich_query_for_embedding(raw_query: str, query: QueryOntology) -> str:
    """
    Build an enriched query string for embedding that incorporates
    extracted attributes to improve semantic search quality.
    """
    parts = [raw_query]

    ea = query.eat_in_attributes
    if ea:
        if ea.desired_cuisine:
            parts.append(ea.desired_cuisine)
        if ea.desired_ingredients:
            parts.extend(ea.desired_ingredients[:5])  # top 5 ingredients
        if ea.mood:
            parts.append(ea.mood)
        if ea.occasion:
            parts.append(ea.occasion)

    # Add inferred mood from query
    if query.inferred_mood:
        parts.append(query.inferred_mood)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main pipeline function
# ---------------------------------------------------------------------------

async def run_eat_in_pipeline(
    raw_query: str,
    user_id: str,
    session_id: str | None = None,
) -> dict:
    """
    Orchestrate all 6 pipeline stages for an eat-in query.

    Stages:
      0. Load user profile from Supabase
      1+2. Extract QueryOntology
      2b. Fuse ontologies → RetrievalContext
      3. Retrieve recipe candidates
      4. Rank candidates
      5. Refine results (the quality gate)
      6. Generate response

    Args:
        raw_query: The user's natural-language query.
        user_id: UUID string of the user.
        session_id: Optional session UUID for context tracking.

    Returns:
        dict with keys:
          - generated_text: str  (the final user-facing response)
          - results: list[dict]  (per-recipe structured data)
          - debug: dict          (pipeline timings, stage outputs, errors)
          - pipeline_status: "ok" | "partial" | "error"
          - error: str | None    (set if pipeline_status != "ok")
    """
    pipeline_start = time.monotonic()
    debug: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "raw_query": raw_query,
        "stage_timings": {},
        "stage_errors": {},
        "recipe_count_after_retrieval": 0,
        "recipe_count_after_ranking": 0,
    }

    # -----------------------------------------------------------------------
    # Stage 0: Load user profile
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    try:
        profile = await _load_profile_from_supabase(user_id)
        if profile is None:
            logger.info("No profile found for user_id=%s — using defaults", user_id)
            profile = _build_default_profile(user_id)
            debug["profile_status"] = "default"
        else:
            debug["profile_status"] = "loaded"
    except Exception as exc:
        logger.error("Stage 0 (profile load) failed: %s", exc)
        profile = _build_default_profile(user_id)
        debug["profile_status"] = "error_fallback"
        debug["stage_errors"]["stage0_profile"] = str(exc)
    debug["stage_timings"]["stage0_profile"] = round(time.monotonic() - t0, 3)

    # -----------------------------------------------------------------------
    # Stage 1+2: Extract QueryOntology
    # -----------------------------------------------------------------------
    t1 = time.monotonic()
    query: QueryOntology | None = None
    try:
        query = await extract_query(raw_query, profile)
        debug["query_complexity"] = query.query_complexity
        debug["ambiguity_score"] = query.ambiguity_score
        debug["conflicts_count"] = len(query.conflicts)
        debug["inferred_mood"] = query.inferred_mood
        debug["inferred_urgency"] = query.inferred_urgency
    except Exception as exc:
        logger.error("Stage 1+2 (query extraction) failed: %s", exc)
        debug["stage_errors"]["stage1_query_extraction"] = str(exc)
        # Minimal fallback query
        query = QueryOntology(
            user_id=profile.user_id,
            raw_query=raw_query,
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(),
        )
    debug["stage_timings"]["stage1_query_extraction"] = round(time.monotonic() - t1, 3)

    # -----------------------------------------------------------------------
    # Off-topic detection: catch non-food queries early
    # -----------------------------------------------------------------------
    _is_off_topic = False
    if query.query_complexity is not None and query.query_complexity <= 0.15:
        ea = query.eat_in_attributes
        has_food_signal = (
            ea is not None
            and (
                ea.desired_cuisine
                or ea.desired_ingredients
                or ea.mood
                or ea.occasion
                or ea.nutritional_goal
                or ea.time_constraint_minutes
            )
        )
        if not has_food_signal:
            _is_off_topic = True

    if _is_off_topic:
        return {
            "generated_text": (
                "I'm a recipe assistant — I can help you find something delicious "
                "to cook. What are you in the mood for?"
            ),
            "results": [],
            "debug": debug,
            "pipeline_status": "off_topic",
            "error": None,
        }

    # -----------------------------------------------------------------------
    # Stage 2b: Fuse ontologies → RetrievalContext
    # -----------------------------------------------------------------------
    t2b = time.monotonic()
    try:
        retrieval_context = fuse_ontologies(profile, query)
        debug["hard_filters_count"] = len(retrieval_context.hard_filters)
        debug["soft_filters_count"] = len(retrieval_context.soft_filters)
        debug["warnings"] = retrieval_context.warnings
    except Exception as exc:
        logger.error("Stage 2b (fusion) failed: %s", exc)
        debug["stage_errors"]["stage2b_fusion"] = str(exc)
        from models.fused_ontology import RetrievalContext
        retrieval_context = RetrievalContext()
    debug["stage_timings"]["stage2b_fusion"] = round(time.monotonic() - t2b, 3)

    # Check for blocking conflicts before proceeding
    if query.requires_clarification if hasattr(query, 'requires_clarification') else False:
        return {
            "generated_text": retrieval_context.clarification_question or "Could you clarify your request?",
            "results": [],
            "debug": debug,
            "pipeline_status": "clarification_needed",
            "error": None,
        }

    if retrieval_context.requires_clarification:
        return {
            "generated_text": retrieval_context.clarification_question or "Could you clarify your request?",
            "results": [],
            "debug": debug,
            "pipeline_status": "clarification_needed",
            "error": None,
        }

    # Check for hard dietary blocks
    blocking_conflicts = query.get_blocking_conflicts()
    if blocking_conflicts:
        block_text = blocking_conflicts[0].description if blocking_conflicts else "Dietary restriction violated."
        # Build a helpful blocked response that explains WHY and suggests alternatives
        block_explanation = (
            f"Your profile has a dietary restriction that conflicts with this query: "
            f"{block_text} "
            f"Here are some alternatives you might enjoy instead: "
            f"try searching for a plant-based version of this dish, "
            f"or ask for a different cuisine with similar flavours."
        )
        return {
            "generated_text": block_explanation,
            "results": [],
            "debug": debug,
            "pipeline_status": "blocked_with_alternatives",
            "error": block_text,
        }

    # -----------------------------------------------------------------------
    # Stage 3: Retrieve recipe candidates
    # -----------------------------------------------------------------------
    t3 = time.monotonic()
    retrieved_recipes: list[dict] = []
    try:
        enriched_query_text = _enrich_query_for_embedding(raw_query, query)
        debug["enriched_query_text"] = enriched_query_text
        retrieved_recipes = await retrieve_recipes(
            query_text=enriched_query_text,
            retrieval_context=retrieval_context,
            top_k=20,
        )
        debug["recipe_count_after_retrieval"] = len(retrieved_recipes)
    except Exception as exc:
        logger.error("Stage 3 (retrieval) failed: %s", exc)
        debug["stage_errors"]["stage3_retrieval"] = str(exc)
        # Cannot recover from retrieval failure
        return {
            "generated_text": (
                "Recipe search is temporarily unavailable. Please try again shortly."
            ),
            "results": [],
            "debug": debug,
            "pipeline_status": "error",
            "error": f"Retrieval failed: {exc}",
        }
    debug["stage_timings"]["stage3_retrieval"] = round(time.monotonic() - t3, 3)

    if not retrieved_recipes:
        # Build a helpful empty-result response explaining which constraints narrowed to zero
        constraint_parts: list[str] = []
        ea = query.eat_in_attributes
        if ea:
            if ea.desired_cuisine:
                constraint_parts.append(f"cuisine: {ea.desired_cuisine}")
            if ea.desired_ingredients:
                constraint_parts.append(f"ingredients: {', '.join(ea.desired_ingredients[:3])}")
            if ea.time_constraint_minutes:
                constraint_parts.append(f"time limit: {ea.time_constraint_minutes} min")
            if ea.difficulty_constraint:
                constraint_parts.append(f"difficulty: {ea.difficulty_constraint}")
            if ea.nutritional_goal:
                constraint_parts.append(f"nutritional goal: {ea.nutritional_goal}")
        # Include hard filters from fusion
        hard_filter_labels = [f.label if hasattr(f, 'label') else str(f) for f in retrieval_context.hard_filters[:3]]
        if hard_filter_labels:
            constraint_parts.append(f"dietary filters: {', '.join(hard_filter_labels)}")

        if constraint_parts:
            constraint_summary = ", ".join(constraint_parts)
            empty_text = (
                f"No recipes matched all of your constraints ({constraint_summary}). "
                f"Try relaxing one constraint — for example, remove the time limit "
                f"or broaden the cuisine. The more constraints you combine, the fewer "
                f"matches are possible."
            )
        else:
            empty_text = (
                "No recipes were found matching your query. "
                "Try broadening your search or adjusting your ingredients."
            )
        return {
            "generated_text": empty_text,
            "results": [],
            "debug": debug,
            "pipeline_status": "no_results",
            "error": None,
        }

    # -----------------------------------------------------------------------
    # Stage 4: Rank candidates
    # -----------------------------------------------------------------------
    t4 = time.monotonic()
    ranked_recipes: list[dict] = []
    try:
        ranked_recipes = rank_recipes(
            recipes=retrieved_recipes,
            profile=profile,
            query=query,
            retrieval_context=retrieval_context,
            top_n=5,
        )
        debug["recipe_count_after_ranking"] = len(ranked_recipes)
        debug["top_match_score"] = ranked_recipes[0].get("_match_score") if ranked_recipes else None
    except Exception as exc:
        logger.error("Stage 4 (ranking) failed: %s", exc)
        debug["stage_errors"]["stage4_ranking"] = str(exc)
        # Fallback: use retrieval order
        ranked_recipes = retrieved_recipes[:5]
        for r in ranked_recipes:
            r.setdefault("_match_score", r.get("_similarity", 0.0))
            r.setdefault("_match_tier", "stretch_pick")
    debug["stage_timings"]["stage4_ranking"] = round(time.monotonic() - t4, 3)

    # -----------------------------------------------------------------------
    # Stage 5: Refinement agent
    # -----------------------------------------------------------------------
    t5 = time.monotonic()
    refined_context: str = ""
    try:
        refined_context = await refine_results(
            ranked_recipes=ranked_recipes,
            query=query,
            profile=profile,
            retrieval_context=retrieval_context,
        )
        debug["refined_context_length"] = len(refined_context)
    except Exception as exc:
        logger.error("Stage 5 (refinement) failed: %s", exc)
        debug["stage_errors"]["stage5_refinement"] = str(exc)
        # Minimal fallback context
        recipe_titles = [r.get("title_en") or r.get("title") or "Recipe" for r in ranked_recipes]
        refined_context = (
            f"[CONTEXT FOR GENERATION]\n\n"
            f"USER QUERY: {raw_query}\n\n"
            f"PROFILE CONSTRAINTS:\n{_summarise_profile_constraints_simple(profile)}\n\n"
            f"WARNINGS:\nRefinement agent unavailable — results may be less precise.\n\n"
            f"CANDIDATE RECIPES:\n"
            + "\n".join(f"- {t}" for t in recipe_titles)
            + "\n\nEND OF CONTEXT"
        )
    debug["stage_timings"]["stage5_refinement"] = round(time.monotonic() - t5, 3)

    # -----------------------------------------------------------------------
    # Stage 6: Generate response
    # -----------------------------------------------------------------------
    t6 = time.monotonic()
    response: dict = {}
    try:
        response = await generate_response(
            refined_context=refined_context,
            query=query,
            profile=profile,
            ranked_recipes=ranked_recipes,
        )
    except Exception as exc:
        logger.error("Stage 6 (generation) failed: %s", exc)
        debug["stage_errors"]["stage6_generation"] = str(exc)
        # Minimal fallback
        titles = [r.get("title_en") or r.get("title") or "Recipe" for r in ranked_recipes]
        response = {
            "generated_text": (
                f"Here are the closest matches to your query: "
                f"{', '.join(titles[:3])}."
            ),
            "results": [
                {
                    "recipe_id": r.get("_entity_id", ""),
                    "title": r.get("title_en") or r.get("title") or "Recipe",
                    "match_score": r.get("_match_score", 0.0),
                    "match_tier": r.get("_match_tier", "stretch_pick"),
                    "time_total_min": r.get("time_total_min"),
                    "difficulty": r.get("difficulty"),
                    "serves": r.get("serves"),
                    "missing_ingredients": [],
                    "substitutions": [],
                    "warnings": [],
                }
                for r in ranked_recipes
            ],
        }
    debug["stage_timings"]["stage6_generation"] = round(time.monotonic() - t6, 3)

    # -----------------------------------------------------------------------
    # Assemble final output
    # -----------------------------------------------------------------------
    total_time = round(time.monotonic() - pipeline_start, 3)
    debug["total_time_seconds"] = total_time

    pipeline_status = "ok"
    if debug["stage_errors"]:
        pipeline_status = "partial" if response.get("generated_text") else "error"

    logger.info(
        "Eat In pipeline complete: status=%s, recipes=%d, time=%.2fs",
        pipeline_status,
        len(response.get("results", [])),
        total_time,
    )

    return {
        "generated_text": response.get("generated_text", ""),
        "results": response.get("results", []),
        "debug": debug,
        "pipeline_status": pipeline_status,
        "error": None if not debug["stage_errors"] else str(debug["stage_errors"]),
    }


# ---------------------------------------------------------------------------
# Helper for fallback profile constraint summary
# ---------------------------------------------------------------------------

def _summarise_profile_constraints_simple(profile: UserProfile) -> str:
    """Minimal constraint summary for emergency fallback contexts."""
    hard_stops = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    if hard_stops:
        return f"Hard stops: {', '.join(hard_stops)}"
    return "No specific dietary restrictions."
