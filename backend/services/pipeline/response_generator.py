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
        ranked_recipes: list[dict] | None = None,
    ) -> dict

Returns:
    {
        "generated_text": str,
        "results": list[dict]   # per-recipe structured data
    }

Style rules from miam master plan:
- EU/British English throughout
- All measurements metric, temperatures Celsius
- No exclamation marks, no emoji, no sign-off
- Warm, knowledgeable, concise tone
- Respects [ONTOLOGY DIRECTIVES] from refined context
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

# Valid match tier values including new creative tiers
_VALID_MATCH_TIERS = frozenset({
    "full_match",
    "close_match",
    "stretch_pick",
    "generated",   # new recipe created by the agent
    "adapted",     # existing recipe modified for the user
})


def _strip_exclamations(text: str) -> str:
    """Replace '!' at sentence boundaries with '.'.

    Uses a lookahead so only '!' followed by whitespace or end-of-string is
    replaced, preserving '?!' sequences correctly:
        'Great dish!'   -> 'Great dish.'
        'What?!'        -> 'What?.'
        'Hello! World!' -> 'Hello. World.'

    The naive .replace('!', '.') would turn 'What?!' into 'What?.', which
    is why this regex helper is used instead.
    """
    return re.sub(r'!(?=\s|$)', '.', text)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_RESPONSE_GENERATION_SYSTEM_PROMPT = """\
You are the Response Generator of the miam food intelligence system.
You receive a structured context document produced by the Refinement Agent
and produce the final user-facing response.

INPUTS:
You receive ONLY the [ONTOLOGY SUMMARY] / [ONTOLOGY DIRECTIVES] / [RECIPES & TECHNIQUES] /
[CAVEATS & GAPS] context block. You have no access to the original database.

YOUR CAPABILITIES:
- You CAN suggest existing recipes from the context if they are already a strong match.
- You CAN create a new recipe adapted from context recipes, tailored to the user's profile.
- You CAN combine techniques from multiple context recipes into a new suggestion.
- You CAN answer open-ended food questions (technique queries, ingredient questions)
  grounded in the method steps and technique tags from the context.
- You MUST NOT invent nutrition data not present in the context.
- You MUST NOT include any ingredient that violates a dietary hard stop listed in the context.

AUTHORITY HIERARCHY:
1. Dietary hard stops from [ONTOLOGY SUMMARY]: absolute. Never override.
2. [ONTOLOGY DIRECTIVES]: follow all four lines (Address, Shape, Respect, Weigh, Avoid).
3. Generation guidance from [CAVEATS & GAPS]: follow Emphasise, Caveat, and Approach.
4. Context recipe data: primary evidence for ingredients, techniques, and timings.
5. Your culinary knowledge: use to fill gaps, suggest adaptations, explain techniques.
   When context data and general knowledge conflict, prefer context.

STYLE RULES (non-negotiable):
1. Follow the framing set by [ONTOLOGY DIRECTIVES] Address and Shape.
2. Lead with the most relevant or best-fitting recommendation.
3. Adapt to the user's skill level -- do not describe advanced techniques to a beginner
   without simplifying them.
4. Include approximate timing and difficulty for each recipe suggested.
5. Include a nutrition snapshot per recipe when the data is present in the context;
   if absent, omit -- do not invent numbers.
6. State any WARN compliance issues from the context explicitly and suggest the
   adaptation noted.
7. State pantry gaps (ingredients the user likely needs to buy) explicitly.
8. No exclamation marks. No emoji. No closing line or sign-off.
9. EU/British English: aubergine (not eggplant), courgette (not zucchini),
   coriander (not cilantro), spring onion (not scallion), hob (not stovetop),
   grill (not broil).
10. All measurements metric. Temperatures in Celsius.
11. Warm, knowledgeable, concise. Target 200-400 words for generated_text.

OUTPUT FORMAT -- respond with ONLY valid JSON, no markdown fences, no prose outside JSON:
{
  "generated_text": "<single string -- the full user-facing response>",
  "results": [
    {
      "recipe_id": "<entity_id from context, or 'generated' for new recipes>",
      "title": "<dish title>",
      "match_score": <float 0.0-1.0>,
      "match_tier": "<full_match|close_match|stretch_pick|generated|adapted>",
      "time_total_min": <int or null>,
      "difficulty": <int 1-5 or null>,
      "serves": <int or null>,
      "nutrition_summary": "<e.g. '~420 kcal, 28g protein per serving' -- only if in context, else null>",
      "key_technique": "<one practical, actionable cooking note>",
      "missing_ingredients": ["<ingredient>", ...],
      "substitutions": ["<substitution note>", ...],
      "warnings": ["<warning text>", ...]
    }
  ]
}

For generated or adapted recipes, set recipe_id to "generated" and match_tier to
"generated" or "adapted" accordingly. Set match_score to a reasonable estimate
based on how well the suggestion fits the query and profile.

Keep generated_text to 200-400 words. Each result entry should read as a cohesive
practical note, not a list of bullet points.
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
    Uses ranking metadata from ranked_recipes_meta.
    """
    results: list[dict] = []

    for recipe in ranked_recipes_meta:
        results.append({
            "recipe_id":           recipe.get("_entity_id", "unknown"),
            "title":               recipe.get("title_en") or recipe.get("title") or "Recipe",
            "match_score":         round(float(recipe.get("_match_score") or 0.0), 4),
            "match_tier":          recipe.get("_match_tier") or "stretch_pick",
            "time_total_min":      recipe.get("time_total_min"),
            "difficulty":          recipe.get("difficulty"),
            "serves":              recipe.get("serves"),
            "nutrition_summary":   None,
            "key_technique":       None,
            "missing_ingredients": [],
            "substitutions":       [],
            "warnings":            [],
        })

    recipe_list = ", ".join(r["title"] for r in results) if results else "no results"
    generated_text = (
        f"Based on your query, the closest matching recipes are: {recipe_list}. "
        f"Full details are temporarily unavailable due to a service interruption."
    )

    return {
        "generated_text": generated_text,
        "results":        results,
    }


# ---------------------------------------------------------------------------
# JSON extraction with fallback
# ---------------------------------------------------------------------------

def _extract_json_response(raw: str) -> dict:
    """Extract and validate JSON from LLM output."""
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Extract first JSON object
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {raw[:200]}")


def _validate_and_normalise_response(parsed: dict, ranked_recipes: list[dict]) -> dict:
    """
    Validate the LLM response structure and normalise types.
    Patches missing fields from ranked_recipes metadata where possible.
    Accepts the new match_tier values: generated, adapted, full_match, close_match, stretch_pick.
    """
    # Build lookup from entity IDs for metadata fallback
    recipe_meta_lookup: dict[str, dict] = {}
    for r in ranked_recipes:
        eid = r.get("_entity_id") or ""
        if eid:
            recipe_meta_lookup[eid] = r

    generated_text = str(parsed.get("generated_text") or "").strip()
    # Enforce no exclamation marks -- regex preserves 'What?!' -> 'What?.'
    generated_text = _strip_exclamations(generated_text)

    results_raw = parsed.get("results") or []
    results: list[dict] = []

    for i, item in enumerate(results_raw):
        recipe_id = str(item.get("recipe_id") or "")
        # For generated/adapted recipes recipe_id may be "generated" -- no metadata to look up
        meta = recipe_meta_lookup.get(recipe_id) or {}

        title = item.get("title") or meta.get("title_en") or meta.get("title") or f"Recipe {i + 1}"

        match_score = item.get("match_score")
        if match_score is None:
            match_score = meta.get("_match_score", 0.0)

        raw_tier = item.get("match_tier") or meta.get("_match_tier") or "stretch_pick"
        match_tier = raw_tier if raw_tier in _VALID_MATCH_TIERS else "stretch_pick"

        time_total = item.get("time_total_min") or meta.get("time_total_min")
        difficulty  = item.get("difficulty")     or meta.get("difficulty")
        serves      = item.get("serves")         or meta.get("serves")

        nutrition_summary = item.get("nutrition_summary")
        if isinstance(nutrition_summary, str) and nutrition_summary.strip():
            nutrition_summary = _strip_exclamations(nutrition_summary)
        else:
            nutrition_summary = None

        key_technique = item.get("key_technique")
        if isinstance(key_technique, str):
            key_technique = _strip_exclamations(key_technique).strip() or None
        else:
            key_technique = None

        missing_ings = item.get("missing_ingredients") or []
        if not isinstance(missing_ings, list):
            missing_ings = [str(missing_ings)]

        substitutions = item.get("substitutions") or []
        if not isinstance(substitutions, list):
            substitutions = [str(substitutions)]

        warnings = item.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = [str(warnings)]
        warnings = [_strip_exclamations(w) for w in warnings]

        results.append({
            "recipe_id":           recipe_id,
            "title":               title,
            "match_score":         round(float(match_score), 4) if match_score is not None else 0.0,
            "match_tier":          match_tier,
            "time_total_min":      int(time_total) if time_total is not None else None,
            "difficulty":          int(difficulty) if difficulty is not None else None,
            "serves":              int(serves) if serves is not None else None,
            "nutrition_summary":   nutrition_summary,
            "key_technique":       key_technique,
            "missing_ingredients": missing_ings,
            "substitutions":       substitutions,
            "warnings":            warnings,
        })

    return {
        "generated_text": generated_text,
        "results":        results,
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

    CRITICAL: This function receives ONLY refined_context from Stage 5.
    ranked_recipes is used ONLY for metadata fallback in _validate_and_normalise_response
    and is NOT passed to the LLM.

    Args:
        refined_context: The structured context string from Stage 5.
        query: QueryOntology (for logging and fallback labelling).
        profile: UserProfile (for fallback validation).
        ranked_recipes: Optional metadata list for fallback enrichment. NOT sent to LLM.

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

    messages = [
        {"role": "system", "content": _RESPONSE_GENERATION_SYSTEM_PROMPT},
        {"role": "user",   "content": refined_context},
    ]

    # First attempt
    try:
        raw = await call_llm(
            LLMOperation.RESPONSE_GENERATION,
            messages,
            max_tokens=2048,
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
        logger.warning("Stage 6 LLM call failed (%s) -- retrying with temperature=0", exc)

        try:
            raw = await call_llm(
                LLMOperation.RESPONSE_GENERATION,
                messages,
                temperature=0,
                max_tokens=2048,
            )
            parsed = _extract_json_response(raw)
            result = _validate_and_normalise_response(parsed, ranked_recipes)
            return result

        except Exception as exc2:
            logger.error(
                "Stage 6 failed after retry (%s) -- using deterministic fallback", exc2
            )
            return _build_fallback_response(refined_context, query, ranked_recipes)
