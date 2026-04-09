#!/usr/bin/env python3
"""
eval_llm_judge.py — LLM-as-Judge evaluation for miam pipeline.

Inspired by Pieterjan Pauwelyn's BSc thesis evaluation framework.
Adapted for recipe recommendation: 8 criteria, 1-10 scale, context-blind.

Runs the full pipeline on all 34 eat_in questions, then judges each response
using Mistral Large as evaluator (stays within budget, no paid API needed).

Usage:
    cd backend && python ../scripts/eval_llm_judge.py [--data-source mock|open|combined]

Exception: This script calls Mistral directly for judge evaluation.
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

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(name)s: %(message)s")
logger = logging.getLogger("eval_judge")
logger.setLevel(logging.INFO)

from config import settings
from services.pipeline.eat_in_pipeline import run_eat_in_pipeline
from mistralai.client import Mistral

EVAL_SUITE_PATH = Path(__file__).resolve().parents[1] / "tests" / "eval_suite.json"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "research"
USER_ID = "050d1112-d2bd-4672-8058-0c10ab75a907"

# Judge model — Mistral Large for quality, stays within budget
JUDGE_MODEL = "mistral-large-latest"

# ═══════════════════════════════════════════════════════════════
# EVALUATION PROMPTS (adapted from thesis framework for recipes)
# ═══════════════════════════════════════════════════════════════

JUDGE_SYSTEM_PROMPT = """You are an expert culinary advisor and strict evaluation specialist.
You assess AI-generated recipe recommendation responses.

CRITICAL RULES:
- Score on a 1-10 scale. Use the FULL range. A score of 8+ requires exceptional quality.
- Do NOT default to high scores. Most competent answers should score 5-7.
- A score of 10 means literally perfect — a professional chef and nutritionist would endorse it fully.
- A score of 5 means mediocre — broadly correct but lacking in important ways.
- You are evaluating the RESPONSE ALONE, with no access to the recipe database.
- Respond with valid JSON only."""

EVAL_PROMPT_TEMPLATE = """### EVALUATION TASK

Evaluate this recipe recommendation response on 8 criteria (1-10 scale each).

**User Query:**
{question}

**System Response:**
{answer}

### CRITERIA AND RUBRICS

1. **Recipe Relevance** (1-10)
   Do the recommended recipes match what the user asked for? Correct cuisine, ingredients, dietary needs?
   1-3: Completely off-topic recipes, wrong cuisine or ignored constraints
   4-5: Partially relevant but misses key aspects of the query
   6-7: Mostly relevant with minor mismatches
   8-10: Precisely targeted recipes that directly address the query

2. **Dietary Accuracy** (1-10)
   Are dietary claims correct? If user asked for vegan/halal/gluten-free, are ALL suggestions compliant?
   1-3: Suggests recipes that violate stated dietary requirements
   4-5: Some recipes comply but others may not, unclear about restrictions
   6-7: Most recipes comply, minor uncertainties acknowledged
   8-10: All recipes fully comply with dietary requirements, explicitly confirms compliance

3. **Culinary Authenticity** (1-10)
   Are the recipes authentic to their claimed cuisine? Correct techniques, traditional ingredients?
   1-3: Recipes are inauthentic or culturally inappropriate
   4-5: Generic or westernised versions without acknowledging it
   6-7: Reasonably authentic with some adaptations noted
   8-10: Truly authentic recipes with correct regional techniques and ingredients

4. **Practical Usefulness** (1-10)
   Can the user actually cook from this? Clear timing, ingredients with quantities, skill-appropriate?
   1-3: Vague suggestions without actionable detail
   4-5: Some useful info but missing key details (timing, quantities, technique)
   6-7: Reasonably actionable with most needed information
   8-10: Highly actionable — clear steps, timing, shopping list implications, difficulty level

5. **Nutritional Awareness** (1-10)
   Does the response show awareness of nutritional content where relevant?
   1-3: No nutritional awareness despite it being relevant to the query
   4-5: Vague health claims without specifics
   6-7: Some nutritional context provided
   8-10: Specific nutritional information, calorie awareness, balanced meal suggestions

6. **Response Quality** (1-10)
   Is the response well-structured, concise, and easy to follow?
   1-3: Messy, repetitive, or confusingly structured
   4-5: Basic structure but could be more concise or better organised
   6-7: Well-structured with clear recipe separation
   8-10: Excellent structure — concise intro, clear per-recipe entries, no filler

7. **Constraint Handling** (1-10)
   Does the response respect time constraints, ingredient availability, difficulty preferences?
   1-3: Ignores stated constraints (suggests 2-hour recipe when user said 20 minutes)
   4-5: Partially respects constraints
   6-7: Mostly respects constraints, minor violations acknowledged
   8-10: Fully respects all stated constraints, explicitly confirms compliance

8. **Personalisation** (1-10)
   Does the response feel tailored to the user's specific situation rather than generic?
   1-3: Generic response that could apply to anyone
   4-5: Some acknowledgment of user context
   6-7: Reasonably personalised with relevant suggestions
   8-10: Clearly tailored — references user's specific ingredients, time, preferences, skill level

### OUTPUT FORMAT

Respond with this exact JSON structure:
{{
  "scores": {{
    "recipe_relevance": <int 1-10>,
    "dietary_accuracy": <int 1-10>,
    "culinary_authenticity": <int 1-10>,
    "practical_usefulness": <int 1-10>,
    "nutritional_awareness": <int 1-10>,
    "response_quality": <int 1-10>,
    "constraint_handling": <int 1-10>,
    "personalisation": <int 1-10>
  }},
  "justification": "<2-3 sentences explaining key strengths and weaknesses>",
  "strongest_aspect": "<which criterion scored highest and why>",
  "weakest_aspect": "<which criterion scored lowest and why>"
}}"""

CRITERIA = [
    "recipe_relevance", "dietary_accuracy", "culinary_authenticity",
    "practical_usefulness", "nutritional_awareness", "response_quality",
    "constraint_handling", "personalisation",
]


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


async def judge_response(
    mistral: Mistral,
    question: str,
    answer: str,
    max_retries: int = 3,
) -> dict:
    """Call judge model to evaluate a pipeline response."""
    prompt = EVAL_PROMPT_TEMPLATE.format(question=question, answer=answer)

    for attempt in range(max_retries):
        try:
            response = await asyncio.wait_for(
                mistral.chat.complete_async(
                    model=JUDGE_MODEL,
                    messages=[
                        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                ),
                timeout=45.0,
            )
            raw = response.choices[0].message.content
            return json.loads(raw)
        except Exception as e:
            wait = 2 ** attempt + 1
            logger.warning("Judge attempt %d failed: %s (wait %ds)", attempt + 1, str(e)[:60], wait)
            await asyncio.sleep(wait)

    # Return neutral scores on failure
    return {
        "scores": {c: 5 for c in CRITERIA},
        "justification": "Judge evaluation failed after retries",
        "strongest_aspect": "N/A",
        "weakest_aspect": "N/A",
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-source", type=str, default="combined",
                        help="mock | open | combined")
    args = parser.parse_args()

    data_source = args.data_source
    settings.DATA_SOURCE = data_source

    questions = load_eat_in_questions()
    logger.info("Loaded %d eat_in questions, DATA_SOURCE=%s", len(questions), data_source)

    mistral = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))
    results = []
    progress_path = OUTPUT_DIR / f"_judge_progress_{data_source}.json"

    # Resume support
    done_ids = set()
    if progress_path.exists():
        with open(progress_path) as f:
            results = json.load(f)
        done_ids = {r["question_id"] for r in results}
        logger.info("Resuming: %d already done", len(done_ids))

    remaining = [q for q in questions if q["id"] not in done_ids]
    logger.info("%d questions remaining", len(remaining))

    for i, q in enumerate(remaining):
        qid = q["id"]
        query = q["query"]
        cat = q["_category"]

        logger.info("[%d/%d] %s (%s): %s",
                    len(results) + 1, len(questions), qid, cat, query[:50])

        # Run pipeline
        t0 = time.monotonic()
        try:
            pipeline_result = await asyncio.wait_for(
                run_eat_in_pipeline(raw_query=query, user_id=USER_ID),
                timeout=90.0,
            )
        except Exception as exc:
            logger.error("Pipeline failed on %s: %s", qid, exc)
            pipeline_result = {
                "generated_text": f"Pipeline error: {exc}",
                "results": [],
                "pipeline_status": "error",
            }
        pipeline_time = time.monotonic() - t0

        gen_text = pipeline_result.get("generated_text", "")
        result_count = len(pipeline_result.get("results", []))

        logger.info("  Pipeline: %d results, %.1fs, %d chars",
                    result_count, pipeline_time, len(gen_text))

        # Judge the response
        t1 = time.monotonic()
        judge_result = await judge_response(mistral, query, gen_text)
        judge_time = time.monotonic() - t1

        scores = judge_result.get("scores", {})
        overall = sum(scores.get(c, 5) for c in CRITERIA) / len(CRITERIA)

        logger.info("  Judge: overall=%.1f, time=%.1fs", overall, judge_time)

        entry = {
            "question_id": qid,
            "category": cat,
            "query": query,
            "data_source": data_source,
            "pipeline_time_s": round(pipeline_time, 2),
            "judge_time_s": round(judge_time, 2),
            "result_count": result_count,
            "pipeline_status": pipeline_result.get("pipeline_status", "unknown"),
            "generated_text": gen_text[:500],  # Truncate for storage
            "scores": scores,
            "overall": round(overall, 2),
            "justification": judge_result.get("justification", ""),
            "strongest_aspect": judge_result.get("strongest_aspect", ""),
            "weakest_aspect": judge_result.get("weakest_aspect", ""),
        }
        results.append(entry)

        # Save progress after each question
        with open(progress_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        # Rate limit
        await asyncio.sleep(1.0)

    # Save final results
    out_path = OUTPUT_DIR / f"eval_judge_{data_source}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"LLM-AS-JUDGE RESULTS — DATA_SOURCE={data_source}")
    print(f"{'=' * 70}")

    overall_scores = [r["overall"] for r in results]
    print(f"Overall: {sum(overall_scores)/len(overall_scores):.2f} (n={len(results)})")

    print(f"\nPer-criterion means:")
    for c in CRITERIA:
        vals = [r["scores"].get(c, 5) for r in results]
        print(f"  {c:30s}: {sum(vals)/len(vals):.2f}")

    print(f"\nPer-category:")
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["overall"])
    for cat, scores in sorted(by_cat.items()):
        print(f"  {cat:25s}: {sum(scores)/len(scores):.2f} (n={len(scores)})")

    print(f"\nTiming: pipeline avg={sum(r['pipeline_time_s'] for r in results)/len(results):.1f}s, "
          f"judge avg={sum(r['judge_time_s'] for r in results)/len(results):.1f}s")

    # Cleanup progress
    if progress_path.exists():
        progress_path.unlink()

    logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    asyncio.run(main())
