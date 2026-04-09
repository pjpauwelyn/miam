"""
Stage 5: Refinement Agent — CRITICAL

THE MOST IMPORTANT PIPELINE RULE:
The generation agent (Stage 6) NEVER receives raw retrieved documents.
This agent produces the ONLY input to Stage 6.

This stage:
1. Assesses each ranked recipe's relevance to the query and profile
2. Scores completeness (identifies missing fields)
3. Extracts the most relevant information selectively
4. Infers reasonable values for missing data, flagging all inferences
5. Constructs a single structured context string for Stage 6

Function signature:
    async def refine_results(
        ranked_recipes: list[dict],
        query: QueryOntology,
        profile: UserProfile,
        retrieval_context: RetrievalContext,
    ) -> str
"""
from __future__ import annotations

import logging
from typing import Any

from models.fused_ontology import RetrievalContext
from models.personal_ontology import UserProfile
from models.query_ontology import QueryOntology
from services.llm_router import LLMOperation, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for refinement agent
# ---------------------------------------------------------------------------

_REFINEMENT_SYSTEM_PROMPT = """\
You are the Refinement Agent of the miam food intelligence system. \
Your sole purpose is to transform ranked recipe candidates into a \
structured, curated context string that the Response Generator (Stage 6) \
will use as its ONLY input.

CRITICAL RULES:
1. You are the information quality gate. Stage 6 sees nothing except what you write.
2. Select and summarise — never dump raw recipe data verbatim.
3. If a field is missing from the recipe data, make a reasonable culinary inference \
   and FLAG it explicitly with [INFERRED: <reason>].
4. Do NOT invent specific timings, exact ingredients, or nutrition numbers — \
   only infer categorical values (e.g. difficulty, typical cuisine flavors).
5. Always state relevance clearly: why does this recipe match the user's query?
6. Include the profile's hard stops in the constraints reminder so Stage 6 cannot \
   accidentally violate them.
7. Format your output EXACTLY as specified below — Stage 6 parses this structure.
8. Use EU/British English for all ingredient names \
   (aubergine, courgette, coriander, spring onion).
9. No markdown headers, no bullet nesting beyond two levels.

OUTPUT FORMAT:
[CONTEXT FOR GENERATION]

USER QUERY: {raw_query}

PROFILE CONSTRAINTS:
{profile_constraints}

WARNINGS:
{warnings}

CANDIDATE RECIPES:
{recipe_sections}

END OF CONTEXT
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarise_profile_constraints(profile: UserProfile) -> str:
    """Build a compact constraint reminder for the refinement system prompt."""
    lines: list[str] = []

    hard_stops = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    if hard_stops:
        lines.append(f"HARD STOPS (never include): {', '.join(hard_stops)}")

    soft_stops = [r.label for r in profile.dietary.soft_stops if not r.is_hard_stop]
    if soft_stops:
        lines.append(f"Soft stops (prefer avoid): {', '.join(soft_stops)}")

    if profile.dietary.spectrum_label:
        lines.append(f"Dietary identity: {profile.dietary.spectrum_label}")

    skill = profile.cooking.skill.value
    weeknight = profile.cooking.weeknight_minutes
    lines.append(f"Cooking skill: {skill}, weeknight time budget: {weeknight} min")

    return "\n".join(lines) if lines else "No specific constraints noted."


def _extract_key_ingredients(recipe: dict, max_items: int = 8) -> list[str]:
    """Extract the most important ingredient names from a recipe."""
    names: list[str] = []
    for ing in (recipe.get("ingredients") or []):
        if isinstance(ing, dict):
            name = ing.get("name") or ""
            is_optional = ing.get("is_optional", False)
            if name and not is_optional:
                names.append(name)
        elif isinstance(ing, str):
            names.append(ing)
        if len(names) >= max_items:
            break
    return names


def _extract_nutrition_summary(recipe: dict) -> str | None:
    """Extract a brief nutrition summary if available."""
    nutr = recipe.get("nutrition_per_serving")
    if not nutr:
        return None
    if isinstance(nutr, dict):
        kcal = nutr.get("kcal")
        protein = nutr.get("protein_g")
        if kcal:
            parts = [f"{kcal} kcal"]
            if protein:
                parts.append(f"{protein}g protein")
            return ", ".join(parts) + " per serving"
    return None


def _assess_completeness(recipe: dict) -> dict[str, bool]:
    """Check which key fields are present in the recipe."""
    return {
        "has_title":        bool(recipe.get("title") or recipe.get("title_en")),
        "has_description":  bool(recipe.get("description")),
        "has_ingredients":  bool(recipe.get("ingredients")),
        "has_steps":        bool(recipe.get("steps")),
        "has_time":         recipe.get("time_total_min") is not None,
        "has_difficulty":   recipe.get("difficulty") is not None,
        "has_cuisine":      bool(recipe.get("cuisine_tags")),
        "has_dietary_flags": bool(recipe.get("dietary_flags")),
        "has_nutrition":    bool(recipe.get("nutrition_per_serving")),
        "has_flavor_tags":  bool(recipe.get("flavor_tags")),
    }


def _infer_missing_values(recipe: dict, completeness: dict[str, bool]) -> dict[str, str]:
    """
    Infer reasonable values for missing fields. Returns a dict of
    {field_name: inferred_value_string}.

    All inferences must be flagged with [INFERRED] in the output.
    """
    inferences: dict[str, str] = {}
    cuisine_tags = recipe.get("cuisine_tags") or []

    if not completeness["has_time"]:
        # Infer from steps count
        steps = recipe.get("steps") or []
        if len(steps) <= 3:
            inferences["time_total_min"] = "~20 min [INFERRED: few steps → quick recipe]"
        elif len(steps) <= 6:
            inferences["time_total_min"] = "~40 min [INFERRED: moderate steps]"
        else:
            inferences["time_total_min"] = "~60+ min [INFERRED: many steps]"

    if not completeness["has_difficulty"]:
        steps = recipe.get("steps") or []
        if len(steps) <= 3:
            inferences["difficulty"] = "easy (1-2/5) [INFERRED: few steps]"
        elif len(steps) <= 6:
            inferences["difficulty"] = "medium (3/5) [INFERRED: moderate steps]"
        else:
            inferences["difficulty"] = "challenging (4/5) [INFERRED: many steps]"

    if not completeness["has_nutrition"]:
        inferences["nutrition"] = "Nutrition data unavailable [INFERRED: not in dataset]"

    return inferences


def _build_recipe_section(
    recipe: dict,
    rank: int,
    query: QueryOntology,
    profile: UserProfile,
) -> str:
    """Build a structured text section for one recipe candidate."""
    completeness = _assess_completeness(recipe)
    inferences = _infer_missing_values(recipe, completeness)

    title = recipe.get("title_en") or recipe.get("title") or "Untitled Recipe"
    entity_id = recipe.get("_entity_id", "unknown")
    match_score = recipe.get("_match_score", 0.0)
    match_tier = recipe.get("_match_tier", "unknown")
    similarity = recipe.get("_similarity", 0.0)

    lines: list[str] = [
        f"--- RECIPE {rank}: {title} ---",
        f"ID: {entity_id}",
        f"Match score: {match_score:.2f} ({match_tier}) | Semantic similarity: {similarity:.3f}",
    ]

    # Relevance reasoning
    ea = query.eat_in_attributes
    relevance_reasons: list[str] = []

    if ea:
        if ea.desired_cuisine:
            cuisine_tags = [c.lower() for c in (recipe.get("cuisine_tags") or [])]
            if any(ea.desired_cuisine.lower() in c for c in cuisine_tags):
                relevance_reasons.append(f"Matches requested cuisine: {ea.desired_cuisine}")

        if ea.desired_ingredients:
            recipe_ings = {
                (ing.get("name") or "").lower() if isinstance(ing, dict) else ing.lower()
                for ing in (recipe.get("ingredients") or [])
            }
            matched = [i for i in ea.desired_ingredients if any(i.lower() in ri for ri in recipe_ings)]
            if matched:
                relevance_reasons.append(f"Contains requested ingredients: {', '.join(matched)}")

        if ea.mood and recipe.get("flavor_tags"):
            relevance_reasons.append(f"Flavor profile suits mood: {ea.mood}")

        if ea.time_constraint_minutes is not None:
            recipe_time = recipe.get("time_total_min")
            if recipe_time and int(recipe_time) <= int(ea.time_constraint_minutes):
                relevance_reasons.append(f"Fits in {ea.time_constraint_minutes} min time constraint")

    if not relevance_reasons:
        relevance_reasons.append("Semantically close match to query intent")

    lines.append(f"Relevance: {'; '.join(relevance_reasons)}")

    # Cuisine
    cuisine = recipe.get("cuisine_tags") or []
    if cuisine:
        lines.append(f"Cuisine: {', '.join(cuisine)}")

    # Time
    if completeness["has_time"]:
        time_val = recipe.get("time_total_min")
        prep = recipe.get("time_prep_min", "?")
        cook = recipe.get("time_cook_min", "?")
        lines.append(f"Time: {time_val} min total (prep {prep} min + cook {cook} min)")
    else:
        lines.append(f"Time: {inferences.get('time_total_min', 'unknown')}")

    # Difficulty
    if completeness["has_difficulty"]:
        diff = recipe.get("difficulty")
        diff_labels = {1: "beginner", 2: "easy", 3: "medium", 4: "advanced", 5: "professional"}
        diff_label = diff_labels.get(diff, str(diff))
        lines.append(f"Difficulty: {diff}/5 ({diff_label})")
    else:
        lines.append(f"Difficulty: {inferences.get('difficulty', 'unknown')}")

    # Serves
    serves = recipe.get("serves")
    if serves:
        lines.append(f"Serves: {serves}")

    # Key ingredients
    key_ings = _extract_key_ingredients(recipe)
    if key_ings:
        lines.append(f"Key ingredients: {', '.join(key_ings)}")
    elif not completeness["has_ingredients"]:
        lines.append("Ingredients: [INFERRED: ingredient list unavailable in dataset]")

    # Flavor and texture tags
    flavor_tags = recipe.get("flavor_tags") or []
    if flavor_tags:
        lines.append(f"Flavor profile: {', '.join(flavor_tags[:5])}")

    texture_tags = recipe.get("texture_tags") or []
    if texture_tags:
        lines.append(f"Texture: {', '.join(texture_tags[:3])}")

    # Dietary flags (brief)
    dietary_flags = recipe.get("dietary_flags") or {}
    if isinstance(dietary_flags, dict):
        active_flags = [k for k, v in dietary_flags.items() if v is True and k.startswith("is_")]
        if active_flags:
            lines.append(f"Dietary: {', '.join(f.replace('is_', '') for f in active_flags)}")

    # Nutrition
    nutr_summary = _extract_nutrition_summary(recipe)
    if nutr_summary:
        lines.append(f"Nutrition: {nutr_summary}")
    else:
        lines.append(f"Nutrition: {inferences.get('nutrition', 'not available')}")

    # Occasion tags
    occasion_tags = recipe.get("occasion_tags") or []
    if occasion_tags:
        lines.append(f"Occasion: {', '.join(occasion_tags[:3])}")

    # Description (truncated)
    description = recipe.get("description") or ""
    if description:
        desc_preview = description[:200] + ("..." if len(description) > 200 else "")
        lines.append(f"Description: {desc_preview}")

    # Factor scores breakdown for quality assessment
    factor_scores = recipe.get("_factor_scores") or {}
    if factor_scores:
        gap_notes: list[str] = []
        if factor_scores.get("dietary_compliance", 1.0) < 0.8:
            gap_notes.append("dietary concern")
        if factor_scores.get("time_fit", 1.0) < 0.5:
            gap_notes.append("time overrun")
        if factor_scores.get("difficulty_match", 1.0) < 0.5:
            gap_notes.append("skill stretch")
        if factor_scores.get("ingredient_overlap", 0.5) < 0.3:
            gap_notes.append("low ingredient overlap")
        if gap_notes:
            lines.append(f"Gaps/concerns: {'; '.join(gap_notes)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main refinement function
# ---------------------------------------------------------------------------

async def refine_results(
    ranked_recipes: list[dict],
    query: QueryOntology,
    profile: UserProfile,
    retrieval_context: RetrievalContext,
) -> str:
    """
    Stage 5: Refinement Agent.

    Produces the structured context string that is the ONLY input to Stage 6.

    CRITICAL: This function is the information quality gate.
    Stage 6 (response_generator) sees nothing except what this function produces.

    Args:
        ranked_recipes: Top-ranked recipes from Stage 4 (with scoring metadata).
        query: QueryOntology from Stage 1+2.
        profile: UserProfile.
        retrieval_context: RetrievalContext from Stage 2b.

    Returns:
        A structured context string starting with [CONTEXT FOR GENERATION].
    """
    if not ranked_recipes:
        logger.warning("Stage 5: No ranked recipes to refine — returning empty context")
        return (
            "[CONTEXT FOR GENERATION]\n\n"
            "USER QUERY: " + query.raw_query + "\n\n"
            "No matching recipes were found for this query.\n\n"
            "END OF CONTEXT"
        )

    # Use top 5 (or fewer if less available)
    recipes_to_refine = ranked_recipes[:5]

    # Build recipe sections (deterministic — no LLM for section building)
    recipe_sections: list[str] = []
    for i, recipe in enumerate(recipes_to_refine, start=1):
        section = _build_recipe_section(recipe, i, query, profile)
        recipe_sections.append(section)

    recipe_sections_text = "\n\n".join(recipe_sections)
    profile_constraints = _summarise_profile_constraints(profile)
    warnings_text = "\n".join(retrieval_context.warnings) or "None"

    # Build the prompt for the refinement LLM call
    system_prompt = _REFINEMENT_SYSTEM_PROMPT.format(
        raw_query=query.raw_query,
        profile_constraints=profile_constraints,
        warnings=warnings_text,
        recipe_sections=recipe_sections_text,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Refine the above {len(recipes_to_refine)} recipe candidates into a "
                f"structured context block for the response generator. "
                f"Assess quality, flag gaps, and ensure the profile constraints are "
                f"honoured. Follow the output format exactly."
            ),
        },
    ]

    try:
        refined_context = await call_llm(
            LLMOperation.REFINEMENT_AGENT,
            messages,
            max_tokens=2048,
        )
        logger.info(
            "Stage 5 complete: refined context length=%d chars",
            len(refined_context),
        )

        # Validate the output starts with the expected header
        if not refined_context.strip().startswith("[CONTEXT FOR GENERATION]"):
            logger.warning(
                "Refinement agent output missing expected header — prepending"
            )
            # Prepend the mandatory header so Stage 6 can always rely on it
            refined_context = "[CONTEXT FOR GENERATION]\n\n" + refined_context

        return refined_context

    except Exception as exc:
        logger.error("Stage 5 LLM call failed (%s) — falling back to deterministic context", exc)

        # Fallback: construct the context deterministically without LLM
        fallback_lines: list[str] = [
            "[CONTEXT FOR GENERATION]",
            "",
            f"USER QUERY: {query.raw_query}",
            "",
            "PROFILE CONSTRAINTS:",
            profile_constraints,
            "",
            "WARNINGS:",
            warnings_text,
            "",
            "CANDIDATE RECIPES:",
            recipe_sections_text,
            "",
            "NOTE: This context was generated without LLM refinement due to a service error.",
            "",
            "END OF CONTEXT",
        ]
        return "\n".join(fallback_lines)
