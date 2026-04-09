"""
Stage 6: Response Generator

Takes ONLY the refinement agent output (never raw documents).
Produces the final structured response for the user.

CRITICAL: This stage receives ONLY the refined_context string from Stage 5.
It never accesses the original retrieved documents or database directly.

Function signature:
    async def generate_response(
        refined_context: str,
        query: QueryOntology,
        profile: UserProfile,
    ) -> dict

Returns:
    {
        "generated_text": str,
        "results": list[dict]   # per-recipe structured data
    }

Style rules from miam master plan:
- 1-sentence intro
- Concise per-recipe entry
- Pantry gaps explicit
- Warnings stated directly
- No exclamation marks, no emoji, no closing line
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from models.personal_ontology import UserProfile
from models.query_ontology import QueryOntology
from services.llm_router import LLMOperation, call_llm, call_llm_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_RESPONSE_GENERATION_SYSTEM_PROMPT = """\
You are the Response Generator of the miam food intelligence system. \
You receive a structured context block produced by the Refinement Agent \
and produce the final user-facing response.

INPUTS: You receive ONLY the [CONTEXT FOR GENERATION] block. \
You have no access to the original database or documents.

STYLE RULES (non-negotiable):
1. Start with a single sentence that directly addresses the query.
2. For each recipe, include: a 2–3 sentence description, approximate total \
   time and difficulty level, and one key practical tip or technique note.
3. Include a brief nutrition snapshot per recipe when available in the context \
   (e.g. "approximately 420 kcal, 28 g protein per serving"). If no nutrition \
   data is in the context, omit — do not invent numbers.
4. State pantry gaps (missing ingredients the user likely needs to buy) explicitly.
5. State any warnings from the context directly — do not soften them.
6. No exclamation marks. No emoji. No closing line or sign-off.
7. Use EU/British English: aubergine, courgette, coriander, spring onion.
8. All measurements metric. Temperatures in Celsius.
9. Do not invent information not in the context.
10. If a field was marked [INFERRED] in the context, reflect that uncertainty \
   naturally in the prose (e.g. "approximately", "likely around").
11. Reference the user's context when relevant — acknowledge time constraints, \
    dietary preferences, skill level, or cuisine interests from the user \
    profile section if provided.

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown, no prose:
{
  "generated_text": "<single string — the full user-facing response>",
  "results": [
    {
      "recipe_id": "<entity_id string>",
      "title": "<recipe title>",
      "match_score": <float>,
      "match_tier": "<full_match|close_match|stretch_pick>",
      "time_total_min": <int or null>,
      "difficulty": <int 1-5 or null>,
      "serves": <int or null>,
      "nutrition_summary": "<e.g. '~420 kcal, 28g protein' or null>",
      "key_technique": "<one practical cooking tip or technique note>",
      "missing_ingredients": ["<ingredient>", ...],
      "substitutions": ["<substitution note>", ...],
      "warnings": ["<warning text>", ...]
    }
  ]
}

The "missing_ingredients" field should list ingredients the user likely needs \
to buy (based on the recipe's ingredient list). If the query mentioned specific \
pantry items, exclude those from missing_ingredients.

Keep "generated_text" to 200–400 words. Each recipe entry should be 3–5 sentences \
including practical detail.
"""


# ---------------------------------------------------------------------------
# Fallback: deterministic response builder
# ---------------------------------------------------------------------------

def _build_fallback_response(
    refined_context: str,
    query: QueryOntology,
    ranked_recipes_meta: list[dict],
) -> dict:
    """
    Build a minimal response deterministically when the LLM call fails.
    Uses the structured metadata embedded in the context.
    """
    results: list[dict] = []

    for recipe in ranked_recipes_meta:
        results.append({
            "recipe_id": recipe.get("_entity_id", "unknown"),
            "title": recipe.get("title_en") or recipe.get("title") or "Recipe",
            "match_score": recipe.get("_match_score", 0.0),
            "match_tier": recipe.get("_match_tier", "stretch_pick"),
            "time_total_min": recipe.get("time_total_min"),
            "difficulty": recipe.get("difficulty"),
            "serves": recipe.get("serves"),
            "missing_ingredients": [],
            "substitutions": [],
            "warnings": [],
        })

    recipe_list = ", ".join(r["title"] for r in results) if results else "no results"
    generated_text = (
        f"Based on your query, here are the closest matching recipes: {recipe_list}. "
        f"Full details are currently unavailable due to a service interruption."
    )

    return {
        "generated_text": generated_text,
        "results": results,
    }


# ---------------------------------------------------------------------------
# JSON extraction with fallback
# ---------------------------------------------------------------------------

def _extract_json_response(raw: str) -> dict:
    """Extract and validate JSON from LLM output."""
    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try stripping markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Try extracting first JSON object
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from response: {raw[:200]}")


def _validate_and_normalise_response(parsed: dict, ranked_recipes: list[dict]) -> dict:
    """
    Validate the LLM response structure and normalise types.
    Patches missing fields from ranked_recipes metadata where possible.
    """
    # Build lookup from any recipe IDs
    recipe_meta_lookup: dict[str, dict] = {}
    for r in ranked_recipes:
        eid = r.get("_entity_id") or ""
        if eid:
            recipe_meta_lookup[eid] = r

    generated_text = str(parsed.get("generated_text") or "").strip()

    # Remove exclamation marks (hard rule)
    generated_text = generated_text.replace("!", ".")

    results_raw = parsed.get("results") or []
    results: list[dict] = []

    for i, item in enumerate(results_raw):
        recipe_id = str(item.get("recipe_id") or "")
        meta = recipe_meta_lookup.get(recipe_id) or {}

        # Fallback values from ranked recipe metadata
        title = item.get("title") or meta.get("title_en") or meta.get("title") or f"Recipe {i+1}"
        match_score = item.get("match_score")
        if match_score is None:
            match_score = meta.get("_match_score", 0.0)
        match_tier = item.get("match_tier") or meta.get("_match_tier") or "stretch_pick"

        time_total = item.get("time_total_min") or meta.get("time_total_min")
        difficulty = item.get("difficulty") or meta.get("difficulty")
        serves = item.get("serves") or meta.get("serves")

        missing_ings = item.get("missing_ingredients") or []
        if not isinstance(missing_ings, list):
            missing_ings = [str(missing_ings)]

        substitutions = item.get("substitutions") or []
        if not isinstance(substitutions, list):
            substitutions = [str(substitutions)]

        warnings = item.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = [str(warnings)]

        # Remove exclamation marks from warnings
        warnings = [w.replace("!", ".") for w in warnings]

        results.append({
            "recipe_id":           recipe_id,
            "title":               title,
            "match_score":         round(float(match_score), 4) if match_score is not None else 0.0,
            "match_tier":          match_tier,
            "time_total_min":      int(time_total) if time_total is not None else None,
            "difficulty":          int(difficulty) if difficulty is not None else None,
            "serves":              int(serves) if serves is not None else None,
            "missing_ingredients": missing_ings,
            "substitutions":       substitutions,
            "warnings":            warnings,
        })

    return {
        "generated_text": generated_text,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_response(
    refined_context: str,
    query: QueryOntology,
    profile: UserProfile,
    ranked_recipes: list[dict] | None = None,
) -> dict:
    """
    Stage 6: Response Generator.

    Generates the final user-facing response from the refinement agent output.

    CRITICAL: This function receives ONLY refined_context — never raw documents.

    Args:
        refined_context: The structured context string from Stage 5.
        query: QueryOntology (for style hints and fallback labelling).
        profile: UserProfile (for style/constraint validation).
        ranked_recipes: Optional list of ranked recipes for fallback
                        metadata enrichment. NOT passed to the LLM.

    Returns:
        dict with keys: "generated_text" (str), "results" (list[dict])
    """
    if not ranked_recipes:
        ranked_recipes = []

    logger.info(
        "Stage 6: generating response (context=%d chars, recipes_meta=%d)",
        len(refined_context),
        len(ranked_recipes),
    )

    # Build a brief query context note for the prompt
    ea = query.eat_in_attributes
    query_hints: list[str] = []
    if ea:
        if ea.desired_cuisine:
            query_hints.append(f"Requested cuisine: {ea.desired_cuisine}")
        if ea.desired_ingredients:
            query_hints.append(f"Desired ingredients: {', '.join(ea.desired_ingredients)}")
        if ea.time_constraint_minutes:
            query_hints.append(f"Time constraint: {ea.time_constraint_minutes} min")
        if ea.mood:
            query_hints.append(f"Mood: {ea.mood}")

    user_message = refined_context
    if query_hints:
        user_message = (
            f"ADDITIONAL QUERY CONTEXT:\n{chr(10).join(query_hints)}\n\n"
            + refined_context
        )

    messages = [
        {"role": "system", "content": _RESPONSE_GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # First attempt
    try:
        raw = await call_llm(
            LLMOperation.RESPONSE_GENERATION,
            messages,
            max_tokens=1024,
        )
        parsed = _extract_json_response(raw)
        result = _validate_and_normalise_response(parsed, ranked_recipes)

        logger.info(
            "Stage 6 complete: generated_text=%d chars, %d result entries",
            len(result.get("generated_text", "")),
            len(result.get("results", [])),
        )
        return result

    except Exception as exc:
        logger.warning("Stage 6 LLM call failed (%s), retrying with temperature=0", exc)

        try:
            raw = await call_llm(
                LLMOperation.RESPONSE_GENERATION,
                messages,
                temperature=0,
                max_tokens=1024,
            )
            parsed = _extract_json_response(raw)
            result = _validate_and_normalise_response(parsed, ranked_recipes)
            return result

        except Exception as exc2:
            logger.error("Stage 6 failed after retry (%s) — using deterministic fallback", exc2)
            return _build_fallback_response(refined_context, query, ranked_recipes)
