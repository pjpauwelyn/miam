"""
Eat In Pipeline Orchestrator  —  Experiment A patch

Only change vs. baseline: passes `query_ontology=query` into retrieve_recipes
so the multi-vector facet decomposition has access to structured query fields.

All other logic is identical to the baseline eat_in_pipeline.py.
This file replaces the orchestrator on the exp/a branch only.
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

SUPABASE_REST_BASE = f"{settings.SUPABASE_URL}/rest/v1"


def _rest_headers() -> dict[str, str]:
    return settings.supabase_rest_headers


async def _load_profile_from_supabase(user_id: str) -> UserProfile | None:
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
            return None
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        profile_data = row.get("profile_data") or {}
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
            except json.JSONDecodeError:
                return None
        if "user_id" not in profile_data:
            profile_data["user_id"] = user_id
        return UserProfile(**profile_data)
    except Exception as exc:
        logger.error("Exception loading profile: %s", exc)
        return None


def _build_default_profile(user_id: str) -> UserProfile:
    return UserProfile(user_id=UUID(user_id))


def _enrich_query_for_embedding(raw_query: str, query: QueryOntology) -> str:
    parts = [raw_query]
    ea = query.eat_in_attributes
    if ea:
        if ea.desired_cuisine:
            parts.append(ea.desired_cuisine)
        if ea.desired_ingredients:
            parts.extend(ea.desired_ingredients[:5])
        if ea.mood:
            parts.append(ea.mood)
        if ea.occasion:
            parts.append(ea.occasion)
    if query.inferred_mood:
        parts.append(query.inferred_mood)
    return " ".join(parts)


async def run_eat_in_pipeline(
    raw_query: str,
    user_id: str,
    session_id: str | None = None,
) -> dict:
    pipeline_start = time.monotonic()
    debug: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "raw_query": raw_query,
        "stage_timings": {},
        "stage_errors": {},
        "recipe_count_after_retrieval": 0,
        "recipe_count_after_ranking": 0,
        "experiment": "exp/a-multi-vector-retrieval",
    }

    # Stage 0: profile
    t0 = time.monotonic()
    try:
        profile = await _load_profile_from_supabase(user_id)
        if profile is None:
            profile = _build_default_profile(user_id)
            debug["profile_status"] = "default"
        else:
            debug["profile_status"] = "loaded"
    except Exception as exc:
        profile = _build_default_profile(user_id)
        debug["profile_status"] = "error_fallback"
        debug["stage_errors"]["stage0_profile"] = str(exc)
    debug["stage_timings"]["stage0_profile"] = round(time.monotonic() - t0, 3)

    # Stage 1+2: extract query
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
        logger.error("Stage 1+2 failed: %s", exc)
        debug["stage_errors"]["stage1_query_extraction"] = str(exc)
        query = QueryOntology(
            user_id=profile.user_id,
            raw_query=raw_query,
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(),
        )
    debug["stage_timings"]["stage1_query_extraction"] = round(time.monotonic() - t1, 3)

    # Off-topic detection
    _is_off_topic = False
    if query.query_complexity is not None and query.query_complexity <= 0.15:
        ea = query.eat_in_attributes
        has_food_signal = (
            ea is not None
            and (ea.desired_cuisine or ea.desired_ingredients or ea.mood
                 or ea.occasion or ea.nutritional_goal or ea.time_constraint_minutes)
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

    # Stage 2b: fusion
    t2b = time.monotonic()
    try:
        retrieval_context = fuse_ontologies(profile, query)
        debug["hard_filters_count"] = len(retrieval_context.hard_filters)
        debug["soft_filters_count"] = len(retrieval_context.soft_filters)
        debug["warnings"] = retrieval_context.warnings
    except Exception as exc:
        logger.error("Stage 2b failed: %s", exc)
        debug["stage_errors"]["stage2b_fusion"] = str(exc)
        from models.fused_ontology import RetrievalContext
        retrieval_context = RetrievalContext()
    debug["stage_timings"]["stage2b_fusion"] = round(time.monotonic() - t2b, 3)

    if getattr(query, "requires_clarification", False) or retrieval_context.requires_clarification:
        return {
            "generated_text": retrieval_context.clarification_question or "Could you clarify your request?",
            "results": [],
            "debug": debug,
            "pipeline_status": "clarification_needed",
            "error": None,
        }

    # Check hard dietary blocks
    blocking_conflicts = [
        c for c in query.conflicts
        if hasattr(c, "conflict_type") and str(c.conflict_type.value) == "HARD_DIETARY_BLOCK"
    ] if query.conflicts else []
    if blocking_conflicts:
        conflict_texts = [c.warning_text or c.description for c in blocking_conflicts]
        return {
            "generated_text": " ".join(filter(None, conflict_texts)) or "No matching recipes found due to dietary constraints.",
            "results": [],
            "debug": debug,
            "pipeline_status": "dietary_block",
            "error": None,
        }

    # Stage 3: retrieve  — EXP A: pass query_ontology for facet decomposition
    t3 = time.monotonic()
    retrieved_recipes: list[dict] = []
    try:
        enriched_query = _enrich_query_for_embedding(raw_query, query)
        retrieved_recipes = await retrieve_recipes(
            enriched_query,
            retrieval_context,
            query_ontology=query,   # <-- the only change vs. baseline
        )
        debug["recipe_count_after_retrieval"] = len(retrieved_recipes)
        if retrieved_recipes:
            debug["retrieval_methods"] = list({
                r.get("_retrieval_method", "unknown") for r in retrieved_recipes
            })
    except Exception as exc:
        logger.error("Stage 3 failed: %s", exc)
        debug["stage_errors"]["stage3_retrieval"] = str(exc)
    debug["stage_timings"]["stage3_retrieval"] = round(time.monotonic() - t3, 3)

    # Stage 4: rank
    t4 = time.monotonic()
    ranked_recipes: list[dict] = []
    try:
        ranked_recipes = rank_recipes(retrieved_recipes, profile, query, retrieval_context)
        debug["recipe_count_after_ranking"] = len(ranked_recipes)
    except Exception as exc:
        logger.error("Stage 4 failed: %s", exc)
        debug["stage_errors"]["stage4_ranking"] = str(exc)
        ranked_recipes = retrieved_recipes[:5]
    debug["stage_timings"]["stage4_ranking"] = round(time.monotonic() - t4, 3)

    if not ranked_recipes:
        return {
            "generated_text": "I couldn't find any recipes that match your request. Try broadening your search or adjusting your filters.",
            "results": [],
            "debug": debug,
            "pipeline_status": "no_results",
            "error": None,
        }

    # Stage 5: refine
    t5 = time.monotonic()
    refined_context = ""
    try:
        refined_context = await refine_results(ranked_recipes, query, profile, retrieval_context)
    except Exception as exc:
        logger.error("Stage 5 failed: %s", exc)
        debug["stage_errors"]["stage5_refinement"] = str(exc)
    debug["stage_timings"]["stage5_refinement"] = round(time.monotonic() - t5, 3)

    # Stage 6: generate
    t6 = time.monotonic()
    response: dict = {}
    try:
        response = await generate_response(refined_context, query, profile, ranked_recipes)
    except Exception as exc:
        logger.error("Stage 6 failed: %s", exc)
        debug["stage_errors"]["stage6_generation"] = str(exc)
        response = {"generated_text": "An error occurred generating the response.", "results": []}
    debug["stage_timings"]["stage6_generation"] = round(time.monotonic() - t6, 3)

    debug["total_time"] = round(time.monotonic() - pipeline_start, 3)

    return {
        "generated_text": response.get("generated_text", ""),
        "results": response.get("results", []),
        "debug": debug,
        "pipeline_status": "ok",
        "error": None,
    }
