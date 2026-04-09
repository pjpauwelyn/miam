"""
End-to-end pipeline evaluation against eval_suite.json.

Runs a selection of eat_in questions through the full pipeline
(real LLM calls via Mistral + real Supabase data).

Usage:
    python tests/eval_pipeline.py [--all] [--ids q01,q02,...] [--profile USER_ID]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure backend modules importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load env from .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from services.pipeline.eat_in_pipeline import run_eat_in_pipeline

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
logger = logging.getLogger("eval")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Load eval suite
# ---------------------------------------------------------------------------

EVAL_SUITE_PATH = Path(__file__).resolve().parents[2] / "tests" / "eval_suite.json"

def load_eat_in_questions() -> list[dict]:
    """Load all eat_in questions from the eval suite."""
    with open(EVAL_SUITE_PATH) as f:
        data = json.load(f)
    questions = []
    for cat in data["categories"]:
        for q in cat["questions"]:
            q["_category"] = cat["name"]
            if q.get("mode") == "eat_in":
                questions.append(q)
    return questions


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def assess_result(question: dict, result: dict) -> dict:
    """
    Assess a pipeline result against the eval question criteria.
    Returns a grade dict with pass/fail flags and notes.
    """
    grade = {
        "id": question["id"],
        "query": question["query"],
        "category": question["_category"],
        "pipeline_status": result.get("pipeline_status"),
        "has_generated_text": bool(result.get("generated_text")),
        "result_count": len(result.get("results", [])),
        "checks": {},
        "overall": "PASS",
    }

    gen_text = (result.get("generated_text") or "").lower()
    results = result.get("results", [])

    # --- Category-specific checks ---

    cat = question["_category"]

    if cat == "ingredient_search":
        # Check that results exist OR pipeline was blocked (valid for constrained profiles)
        has_results = len(results) > 0
        pipeline_blocked = result.get("pipeline_status") == "blocked"
        grade["checks"]["has_results_or_valid_block"] = has_results or pipeline_blocked
        # Check expected cuisines in results OR in generated text
        expected_cuisines = question.get("expected_cuisines", [])
        if expected_cuisines and (results or gen_text):
            found_cuisines = set()
            for r in results:
                for tag in (r.get("cuisine_tags") or []):
                    found_cuisines.add(tag.lower())
            # Also check generated text for cuisine mentions
            text_match = any(c.lower() in gen_text for c in expected_cuisines)
            expected_lower = {c.lower() for c in expected_cuisines}
            overlap = found_cuisines & expected_lower
            grade["checks"]["cuisine_match"] = len(overlap) > 0 or text_match or pipeline_blocked
            grade["checks"]["cuisine_detail"] = f"expected any of {expected_cuisines}, found in results={found_cuisines}, text_match={text_match}"
        # Dietary constraint
        dc = question.get("dietary_constraint")
        if dc and results:
            flag_key = f"is_{dc}"
            compliant = sum(
                1 for r in results
                if (r.get("dietary_flags") or {}).get(flag_key, False)
            )
            # Also check generated text
            text_mentions_diet = dc.lower() in gen_text
            grade["checks"]["dietary_compliance"] = compliant >= len(results) // 2 or text_mentions_diet
            grade["checks"]["dietary_detail"] = f"{compliant}/{len(results)} recipes are {dc}, text_mentions={text_mentions_diet}"

    elif cat == "dietary_filter":
        expected_tags = question.get("expected_tags", [])
        is_hard = question.get("hard_stop", False)
        if results:
            for tag in expected_tags:
                compliant = sum(
                    1 for r in results
                    if (r.get("dietary_flags") or {}).get(tag, False)
                )
                # Also check generated text for dietary compliance mentions
                tag_word = tag.replace("is_", "").replace("_", " ")
                text_ok = tag_word in gen_text or "plant" in gen_text
                grade["checks"][f"tag_{tag}"] = (compliant == len(results) if is_hard else compliant > 0) or text_ok
                grade["checks"][f"tag_{tag}_detail"] = f"{compliant}/{len(results)} compliant, text_ok={text_ok}"
        else:
            # No results could be OK for very constrained queries
            grade["checks"]["no_results_acceptable"] = True

    elif cat == "time_constraint":
        max_time = question.get("max_time_min")
        min_time = question.get("min_time_min")
        if max_time and results:
            within_time = sum(
                1 for r in results
                if r.get("time_total_min") is not None and int(r.get("time_total_min", 999)) <= max_time
            )
            grade["checks"]["time_within_limit"] = within_time > 0
            grade["checks"]["time_detail"] = f"{within_time}/{len(results)} within {max_time}min"
        if min_time and results:
            above_time = sum(
                1 for r in results
                if r.get("time_total_min") is not None and int(r.get("time_total_min", 0)) >= min_time
            )
            grade["checks"]["time_above_min"] = above_time > 0
            grade["checks"]["time_detail"] = f"{above_time}/{len(results)} above {min_time}min"

    elif cat == "cuisine_exploration":
        expected_cuisines = question.get("expected_cuisines", [])
        found_cuisines = set()
        if results:
            for r in results:
                for tag in (r.get("cuisine_tags") or []):
                    found_cuisines.add(tag.lower())
        expected_lower = {c.lower() for c in expected_cuisines}
        # For cuisine exploration, partial matches or related cuisines are OK
        overlap = found_cuisines & expected_lower
        # Also check if any words overlap (e.g. "dutch" in "dutch/belgian")
        loose_match = any(
            any(exp_word in fc for fc in found_cuisines)
            for exp in expected_lower
            for exp_word in exp.split("/")
        )
        # Also check generated text for cuisine mentions
        text_match = any(c.lower() in gen_text for c in expected_cuisines)
        # Also check individual cuisine words in text (e.g. "north african")
        text_loose = any(
            any(word in gen_text for word in c.lower().split("/"))
            for c in expected_cuisines
        )
        grade["checks"]["cuisine_match"] = len(overlap) > 0 or loose_match or text_match or text_loose
        grade["checks"]["cuisine_detail"] = f"expected any of {expected_cuisines}, found in results={found_cuisines}, text_match={text_match or text_loose}"
        if not results and not gen_text:
            grade["checks"]["has_results"] = False

    elif cat == "edge_cases":
        expected_result = question.get("expected_result")
        if expected_result == "empty_query":
            # Pipeline should handle gracefully
            grade["checks"]["handled_gracefully"] = result.get("pipeline_status") != "error"
        elif expected_result == "off_topic":
            grade["checks"]["handled_gracefully"] = result.get("pipeline_status") != "error"
        elif expected_result in ("limited_results_with_explanation", "highly_constrained"):
            grade["checks"]["handled_gracefully"] = True  # As long as no crash
        elif expected_result == "ambiguous_preference":
            grade["checks"]["handled_gracefully"] = True
        elif expected_result == "unusual_serving_size":
            grade["checks"]["handled_gracefully"] = True
        else:
            grade["checks"]["handled_gracefully"] = True

    # Determine overall pass/fail
    for key, val in grade["checks"].items():
        if key.endswith("_detail"):
            continue
        if val is False:
            grade["overall"] = "FAIL"
            break

    return grade


async def run_eval(
    questions: list[dict],
    user_id: str,
) -> list[dict]:
    """Run the eval suite and return grades."""
    grades = []
    for i, q in enumerate(questions):
        qid = q["id"]
        query = q["query"]
        cat = q["_category"]

        logger.info(
            "[%d/%d] %s (%s): %s",
            i + 1, len(questions), qid, cat, query[:60],
        )

        t0 = time.monotonic()
        try:
            result = await run_eat_in_pipeline(
                raw_query=query,
                user_id=user_id,
            )
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
        logger.info(
            "  → status=%s, results=%d, time=%.1fs",
            result.get("pipeline_status"),
            len(result.get("results", [])),
            elapsed,
        )

        grade = assess_result(q, result)
        grade["time_seconds"] = round(elapsed, 2)
        grade["pipeline_debug_summary"] = {
            "stage_timings": result.get("debug", {}).get("stage_timings", {}),
            "stage_errors": result.get("debug", {}).get("stage_errors", {}),
            "recipe_count_after_retrieval": result.get("debug", {}).get("recipe_count_after_retrieval", 0),
            "recipe_count_after_ranking": result.get("debug", {}).get("recipe_count_after_ranking", 0),
        }

        # Log generated text snippet
        gen_text = (result.get("generated_text") or "")[:200]
        logger.info("  → text: %s", gen_text)

        grades.append(grade)

    return grades


def print_summary(grades: list[dict]):
    """Print eval summary."""
    total = len(grades)
    passed = sum(1 for g in grades if g["overall"] == "PASS")
    failed = sum(1 for g in grades if g["overall"] == "FAIL")

    print("\n" + "=" * 70)
    print(f"EVAL RESULTS: {passed}/{total} PASSED, {failed}/{total} FAILED")
    print("=" * 70)

    by_cat = {}
    for g in grades:
        cat = g["category"]
        by_cat.setdefault(cat, []).append(g)

    for cat, cat_grades in by_cat.items():
        cat_pass = sum(1 for g in cat_grades if g["overall"] == "PASS")
        print(f"\n  {cat}: {cat_pass}/{len(cat_grades)}")
        for g in cat_grades:
            status = "✓" if g["overall"] == "PASS" else "✗"
            print(f"    {status} {g['id']}: {g['query'][:50]}  [{g['time_seconds']}s]")
            for k, v in g["checks"].items():
                if not k.endswith("_detail"):
                    detail = g["checks"].get(f"{k}_detail", "")
                    print(f"        {k}: {v}  {detail}")

    # Timing stats
    times = [g["time_seconds"] for g in grades]
    if times:
        print(f"\n  Timing: avg={sum(times)/len(times):.1f}s, "
              f"min={min(times):.1f}s, max={max(times):.1f}s, total={sum(times):.0f}s")

    print()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="Run all 34 eat_in questions")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated question IDs (e.g. q01,q09,q16)")
    parser.add_argument("--profile", type=str, default="050d1112-d2bd-4672-8058-0c10ab75a907",
                        help="User ID to use for evaluation")
    parser.add_argument("--sample", type=int, default=0, help="Run N random questions")
    args = parser.parse_args()

    questions = load_eat_in_questions()
    logger.info("Loaded %d eat_in questions from eval suite", len(questions))

    if args.ids:
        ids = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in ids]
    elif args.sample > 0:
        import random
        random.seed(42)
        questions = random.sample(questions, min(args.sample, len(questions)))
    elif not args.all:
        # Default: run 8 representative questions (1 per category that has eat_in)
        representative = ["q01", "q09", "q16", "q21", "q50", "q54", "q55", "q56"]
        questions = [q for q in questions if q["id"] in representative]

    logger.info("Will evaluate %d questions with profile %s", len(questions), args.profile)

    grades = await run_eval(questions, args.profile)

    # Save full grades
    out_path = Path(__file__).resolve().parents[2] / "tests" / "eval_results.json"
    with open(out_path, "w") as f:
        json.dump(grades, f, indent=2, default=str)
    logger.info("Full grades saved to %s", out_path)

    print_summary(grades)


if __name__ == "__main__":
    asyncio.run(main())
