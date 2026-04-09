#!/usr/bin/env python3
"""
eval_single_config.py — Run eval suite for ONE DATA_SOURCE config.

Usage:
    cd backend && python ../scripts/eval_single_config.py mock
    cd backend && python ../scripts/eval_single_config.py open
    cd backend && python ../scripts/eval_single_config.py combined

Saves to tests/eval_results_config_{letter}.json

Exception: This script calls the Mistral client indirectly through the pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "tests"))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
logger = logging.getLogger("eval")
logger.setLevel(logging.INFO)

from config import settings
from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
from eval_pipeline import assess_result

EVAL_SUITE_PATH = Path(__file__).resolve().parents[1] / "tests" / "eval_suite.json"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tests"
USER_ID = "050d1112-d2bd-4672-8058-0c10ab75a907"
CONFIG_MAP = {"mock": "a", "open": "b", "combined": "c"}


def load_eat_in_questions() -> list[dict]:
    with open(EVAL_SUITE_PATH) as f:
        data = json.load(f)
    questions = []
    for cat in data["categories"]:
        for q in cat["questions"]:
            q["_category"] = cat["name"]
            if q.get("mode") == "eat_in":
                questions.append(q)
    return questions


async def main():
    data_source = sys.argv[1] if len(sys.argv) > 1 else "mock"
    config_label = CONFIG_MAP.get(data_source, "x")

    # Check for resume from progress file
    progress_path = OUTPUT_DIR / f"_eval_progress_{config_label}.json"
    existing_grades = []
    done_ids = set()
    if progress_path.exists():
        with open(progress_path) as f:
            existing_grades = json.load(f)
        done_ids = {g["id"] for g in existing_grades}
        logger.info("Resuming: %d questions already done", len(done_ids))

    settings.DATA_SOURCE = data_source
    questions = load_eat_in_questions()
    remaining = [q for q in questions if q["id"] not in done_ids]

    logger.info("Config %s (%s): %d total, %d remaining",
                config_label.upper(), data_source, len(questions), len(remaining))

    grades = list(existing_grades)

    for i, q in enumerate(remaining):
        qid = q["id"]
        query = q["query"]
        cat = q["_category"]

        logger.info("[%d/%d] %s (%s): %s",
                    len(grades) + 1, len(questions), qid, cat, query[:60])

        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                run_eat_in_pipeline(raw_query=query, user_id=USER_ID),
                timeout=60.0,  # Per-question timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Pipeline timeout on %s", qid)
            result = {
                "generated_text": "",
                "results": [],
                "debug": {"error": "timeout"},
                "pipeline_status": "error",
                "error": "timeout_60s",
            }
        except Exception as exc:
            logger.error("Pipeline crashed on %s: %s", qid, exc)
            result = {
                "generated_text": "",
                "results": [],
                "debug": {"error": str(exc)},
                "pipeline_status": "error",
                "error": str(exc),
            }

        elapsed = time.monotonic() - t0
        logger.info("  → status=%s, results=%d, time=%.1fs",
                    result.get("pipeline_status"),
                    len(result.get("results", [])),
                    elapsed)

        grade = assess_result(q, result)
        grade["time_seconds"] = round(elapsed, 2)
        grade["config"] = config_label
        grade["data_source"] = data_source
        grade["pipeline_debug_summary"] = {
            "stage_timings": result.get("debug", {}).get("stage_timings", {}),
            "stage_errors": result.get("debug", {}).get("stage_errors", {}),
            "recipe_count_after_retrieval": result.get("debug", {}).get("recipe_count_after_retrieval", 0),
            "recipe_count_after_ranking": result.get("debug", {}).get("recipe_count_after_ranking", 0),
        }
        grades.append(grade)

        # Save progress after each question
        with open(progress_path, "w") as f:
            json.dump(grades, f, indent=2, default=str)

    # Save final results
    out_path = OUTPUT_DIR / f"eval_results_config_{config_label}.json"
    with open(out_path, "w") as f:
        json.dump(grades, f, indent=2, default=str)

    # Print summary
    passed = sum(1 for g in grades if g["overall"] == "PASS")
    print(f"\nConfig {config_label.upper()} ({data_source}): {passed}/{len(grades)} PASSED")

    by_cat = {}
    for g in grades:
        by_cat.setdefault(g["category"], []).append(g)
    for cat, cg in by_cat.items():
        cp = sum(1 for g in cg if g["overall"] == "PASS")
        print(f"  {cat}: {cp}/{len(cg)}")

    times = [g["time_seconds"] for g in grades]
    if times:
        print(f"  Timing: avg={sum(times)/len(times):.1f}s, total={sum(times):.0f}s")

    # Cleanup progress
    if progress_path.exists():
        progress_path.unlink()

    logger.info("Done! Results saved to %s", out_path)


if __name__ == "__main__":
    asyncio.run(main())
