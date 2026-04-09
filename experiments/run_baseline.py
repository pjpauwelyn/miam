"""
Baseline Capture Runner
Branch: experiment/baseline-capture

No code changes from main. Run this script to capture the exact broken
pipeline output for the gado gado regression query.

Usage (from repo root, with backend/ on PYTHONPATH):
    cd backend
    python ../experiments/run_baseline.py

The script looks up the user UUID from user_profiles where email = 'pjpauwelyn@gmail.com',
then calls run_eat_in_pipeline with the regression query and writes the result to
experiments/baseline.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Make sure backend/ is on the path when running from repo root
backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(backend_dir))

import httpx
from config import settings

RAW_QUERY = (
    "gado gado with beef mince, sauce packet, already cut vegetables, "
    "the bread. make a recipe for me, you can add ingredients if necessary."
)
TARGET_EMAIL = "pjpauwelyn@gmail.com"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "baseline.json")


async def _lookup_user_id(email: str) -> str:
    """
    Look up the UUID for a given email from user_profiles.
    Raises if not found.
    """
    url = (
        f"{settings.SUPABASE_URL}/rest/v1/user_profiles"
        f"?email=eq.{email}&select=user_id&limit=1"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=settings.supabase_rest_headers)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise ValueError(f"No user_profiles row found for email={email}")
    return rows[0]["user_id"]


def _extract_result_fields(result: dict) -> dict:
    """Extract the fields mandated by the experiment spec."""
    debug = result.get("debug", {})
    raw_results = result.get("results", [])

    result_summaries = [
        {
            "title": r.get("title"),
            "match_tier": r.get("match_tier"),
            "match_score": r.get("match_score"),
        }
        for r in raw_results
    ]

    return {
        "generated_text": result.get("generated_text", ""),
        "results": result_summaries,
        "debug": {
            "enriched_query_text": debug.get("enriched_query_text"),
            "query_complexity": debug.get("query_complexity"),
            "ambiguity_score": debug.get("ambiguity_score"),
            "recipe_count_after_retrieval": debug.get("recipe_count_after_retrieval"),
            "recipe_count_after_ranking": debug.get("recipe_count_after_ranking"),
            "top_match_score": debug.get("top_match_score"),
            "stage_errors": debug.get("stage_errors", {}),
        },
        "top_result_verbatim": raw_results[0] if raw_results else None,
        "pipeline_status": result.get("pipeline_status"),
    }


async def main() -> None:
    print(f"[baseline] Looking up user_id for {TARGET_EMAIL} ...")
    user_id = await _lookup_user_id(TARGET_EMAIL)
    print(f"[baseline] user_id = {user_id}")

    # Import pipeline here so backend settings are already loaded
    from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

    print("[baseline] Running pipeline ...")
    result = await run_eat_in_pipeline(
        raw_query=RAW_QUERY,
        user_id=user_id,
    )

    output = _extract_result_fields(result)
    output["meta"] = {
        "variant": "baseline",
        "raw_query": RAW_QUERY,
        "user_id": user_id,
        "branch": "experiment/baseline-capture",
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, default=str)

    print(f"[baseline] Written to {OUTPUT_FILE}")
    print(f"[baseline] pipeline_status = {result.get('pipeline_status')}")
    if result.get("results"):
        print(f"[baseline] top result title = {result['results'][0].get('title')}")


if __name__ == "__main__":
    asyncio.run(main())
