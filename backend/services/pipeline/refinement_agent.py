"""
Stage 5: Refinement Agent

THE MOST IMPORTANT PIPELINE RULE:
The generation agent (Stage 6) NEVER receives raw retrieved documents.
This agent produces the ONLY input to Stage 6.

This stage:
1. Serialises the complete user ontology and query ontology into structured text
2. Formats ALL recipe data with full ingredients, steps, and nutrition — no truncation
3. Calls the LLM to curate, assess compliance, suggest adaptations, and write directives
4. Produces a structured context document in the canonical [ONTOLOGY SUMMARY] /
   [ONTOLOGY DIRECTIVES] / [RECIPES & TECHNIQUES] / [CAVEATS & GAPS] format
5. Falls back to deterministic construction if the LLM call fails

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
from models.personal_ontology import CookingSkill, PreferenceLevel, UserProfile
from models.query_ontology import QueryOntology
from services.llm_router import LLMOperation, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_REFINEMENT_SYSTEM_PROMPT = """\
You are the Refinement Agent of the miam food intelligence system.
Your sole purpose is to transform ranked recipe candidates, a user's personal
ontology, and their current query into a single structured context document.
This document is the ONLY input the Response Generator (Stage 6) will receive.

CRITICAL RULES:
1. You are the information quality gate. Stage 6 sees nothing except what you write.
2. Actively curate — select the most relevant recipes, assess each against the
   user's profile, identify gaps, suggest adaptations. Do not passively summarise.
3. Respect dietary hard stops absolutely. Flag any WARN for dietary concerns immediately.
4. Assess skill fit: a BEGINNER cannot be expected to execute advanced techniques.
5. Assess time fit: compare recipe time against the user's weeknight/weekend budget.
6. Write the [ONTOLOGY DIRECTIVES] section as explicit instructions for Stage 6 —
   not observations. Use imperative language: "Address:", "Respect:", "Weigh:", "Avoid:".
7. Write the Generation guidance in [CAVEATS & GAPS] as a concrete brief for Stage 6.
8. Use EU/British English: aubergine, courgette, coriander, spring onion, hob.
9. All measurements metric. Temperatures in Celsius.
10. Output ONLY the structured document below — no preamble, no sign-off.

OUTPUT FORMAT (reproduce section headers exactly as written):

[ONTOLOGY SUMMARY]
Profile match factors:
- Dietary: {spectrum_label} | Hard stops: {list or "none"}
- Skill: {level} | Time budget: weeknight {x} min, weekend {x} min
- Equipment: {key equipment or "standard kitchen"}
- Flavour sweet spots: {top preferences with scores, e.g. "umami 8.5, smoky 7.0"}
- Favourite ingredients: {list or "not specified"}
- Cuisine affinities: loves {list} | avoids {list}

Query-specific factors:
- Desired cuisine: {value or "not specified"}
- Desired ingredients: {value or "not specified"}
- Time constraint: {value or "none"}
- Mood / occasion: {value or "not specified"}
- Nutritional goal: {value or "none"}

[ONTOLOGY DIRECTIVES]
Address: {what the user is specifically asking for — concrete and direct}
Shape: {how to frame the answer — skill-appropriate detail level, tone, length}
Respect: {absolute constraints — hard dietary stops, time budget limits}
Weigh: {soft preferences — cuisine affinity, flavour sweet spots, budget range}
Avoid: {things the profile says to skip or de-emphasise}

[RECIPES & TECHNIQUES]
# {Recipe title}
Source ID: {entity_id}
Match: {score} ({tier}) | Why: {1 sentence relevance rationale}

Ingredients ({count}):
- {full list with amounts — every ingredient including optional ones, marked (optional)}

Method ({count} steps):
1. {full instruction text}
...

Key techniques: {technique_tags}
Flavour profile: {flavor_tags} | Texture: {texture_tags}
Time: {total} min ({prep} min prep + {cook} min cook) | Difficulty: {x}/5 | Serves: {x}

Nutrition per serving:
kcal: {value} | protein: {value}g | fat: {value}g | carbs: {value}g | fibre: {value}g | sugar: {value}g | salt: {value}g
(or: Not available in recipe data)

Dietary compliance: PASS
(or: WARN — {specific ingredient or issue}. Adaptation: {concrete suggestion})
Skill fit: GOOD
(or: STRETCH — {specific technique that may challenge this user})
Time fit: FITS
(or: TIGHT — {x} min over budget | OVER — {x} min over budget)
Adaptation notes: {specific, actionable suggestions tailored to this user's profile}

---
{next recipe — repeat the # Title block for each}

[CAVEATS & GAPS]
Ontology coverage:
- Well matched: {attributes that are well covered by the candidates}
- Weak or missing: {gaps — e.g. "no recipes match requested season", "nutrition data absent"}

Data quality:
- {notes on missing or inferred data — flag with [INFERRED] if a value was estimated}

Generation guidance:
- Emphasise: {2-3 specific things Stage 6 should focus on}
- Caveat: {1-2 things Stage 6 should qualify or hedge}
- Approach: {1 sentence framing for the answer — e.g. "Lead with the fastest recipe, mention the dairy-free adaptation upfront"}
"""

# ---------------------------------------------------------------------------
# Helper: serialise user profile
# ---------------------------------------------------------------------------

def _build_profile_summary(profile: UserProfile) -> str:
    """Serialise the complete UserProfile into structured text for the LLM prompt."""
    lines: list[str] = []

    # --- Dietary identity ---
    lines.append("=== DIETARY IDENTITY ===")
    spectrum = profile.dietary.spectrum_label or "not specified"
    lines.append(f"Spectrum label: {spectrum}")

    hard_stops = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    lines.append(f"Hard stops: {', '.join(hard_stops) if hard_stops else 'none'}")

    soft_stops = [r.label for r in profile.dietary.soft_stops if not r.is_hard_stop]
    lines.append(f"Soft stops: {', '.join(soft_stops) if soft_stops else 'none'}")

    if profile.dietary.nuance_notes:
        lines.append(f"Nuance: {profile.dietary.nuance_notes}")

    # --- Cooking context ---
    lines.append("")
    lines.append("=== COOKING CONTEXT ===")
    lines.append(f"Skill level: {profile.cooking.skill.value}")
    lines.append(f"Weeknight time budget: {profile.cooking.weeknight_minutes} min")
    lines.append(f"Weekend time budget: {profile.cooking.weekend_minutes} min")
    lines.append(f"Kitchen setup: {profile.cooking.kitchen_setup.value}")

    eq = profile.cooking.specific_equipment
    owned_equipment = [
        name for name, val in {
            "stand mixer": eq.stand_mixer,
            "food processor": eq.food_processor,
            "sous vide": eq.sous_vide,
            "pressure cooker": eq.pressure_cooker,
            "air fryer": eq.air_fryer,
            "wok": eq.wok,
            "cast iron": eq.cast_iron,
            "outdoor grill": eq.outdoor_grill,
            "pasta machine": eq.pasta_machine,
            "dehydrator": eq.dehydrator,
        }.items() if val
    ]
    lines.append(f"Specific equipment: {', '.join(owned_equipment) if owned_equipment else 'none beyond setup'}")

    # --- Flavour preferences ---
    lines.append("")
    lines.append("=== FLAVOUR PREFERENCES (0-10) ===")
    fl = profile.flavor
    flavor_dims = [
        ("spicy", fl.spicy), ("sweet", fl.sweet), ("sour", fl.sour),
        ("umami", fl.umami), ("bitter", fl.bitter), ("fatty", fl.fatty),
        ("fermented", fl.fermented), ("smoky", fl.smoky), ("salty", fl.salty),
    ]
    for dim, score in flavor_dims:
        score_str = f"{score:.1f}" if score is not None else "not set"
        lines.append(f"{dim}: {score_str}")

    # --- Texture preferences ---
    lines.append("")
    lines.append("=== TEXTURE PREFERENCES (0-10) ===")
    tx = profile.texture
    texture_dims = [
        ("crunchy", tx.crunchy), ("creamy", tx.creamy), ("soft", tx.soft),
        ("chewy", tx.chewy), ("crispy", tx.crispy), ("silky", tx.silky),
        ("chunky", tx.chunky),
    ]
    for dim, score in texture_dims:
        score_str = f"{score:.1f}" if score is not None else "not set"
        lines.append(f"{dim}: {score_str}")

    # --- Cuisine affinities ---
    lines.append("")
    lines.append("=== CUISINE AFFINITIES ===")
    affinity_buckets: dict[str, list[str]] = {
        "loved": [], "liked": [], "neutral": [], "disliked": [], "never": []
    }
    level_map = {
        PreferenceLevel.LOVE: "loved",
        PreferenceLevel.LIKE: "liked",
        PreferenceLevel.NEUTRAL: "neutral",
        PreferenceLevel.DISLIKE: "disliked",
        PreferenceLevel.NEVER: "never",
    }
    for aff in profile.cuisine_affinities.affinities:
        bucket = level_map.get(aff.level, "neutral")
        entry = aff.cuisine
        if aff.sub_nuances:
            entry += f" ({'; '.join(aff.sub_nuances)})"
        affinity_buckets[bucket].append(entry)

    for bucket, entries in affinity_buckets.items():
        if entries:
            lines.append(f"{bucket.capitalize()}: {', '.join(entries)}")

    # --- Budget ---
    lines.append("")
    lines.append("=== BUDGET ===")
    home_budget = f"\u20ac{profile.budget.home_per_meal_eur:.0f}" if profile.budget.home_per_meal_eur is not None else "not set"
    out_budget = f"\u20ac{profile.budget.out_per_meal_eur:.0f}" if profile.budget.out_per_meal_eur is not None else "not set"
    lines.append(f"Home per meal: {home_budget}")
    lines.append(f"Dining out per meal: {out_budget}")

    # --- Adventurousness ---
    lines.append("")
    lines.append("=== ADVENTUROUSNESS ===")
    lines.append(f"Cooking: {profile.adventurousness.cooking_score:.1f}/10")
    lines.append(f"Dining: {profile.adventurousness.dining_score:.1f}/10")

    # --- Nutrition awareness ---
    lines.append("")
    lines.append("=== NUTRITION AWARENESS ===")
    lines.append(f"Level: {profile.nutrition.level.value}")
    if profile.nutrition.tracked_dimensions:
        lines.append(f"Tracked: {', '.join(profile.nutrition.tracked_dimensions)}")

    # --- Social context ---
    lines.append("")
    lines.append("=== SOCIAL CONTEXT ===")
    lines.append(f"Default context: {profile.social.default_social_context.value}")
    lines.append(f"Meals out per week: {profile.social.meals_out_per_week}")
    lines.append(f"Home cooked per week: {profile.social.home_cooked_per_week}")

    # --- Lifestyle ---
    lines.append("")
    lines.append("=== LIFESTYLE ===")
    lines.append(f"Seasonal preference: {profile.lifestyle.seasonal_preference_score:.1f}/10")
    lines.append(f"Sustainability priority: {profile.lifestyle.sustainability_priority_score:.1f}/10")
    if profile.lifestyle.special_interests:
        lines.append(f"Special interests: {', '.join(profile.lifestyle.special_interests)}")
    lines.append(f"Inspiration style: {profile.lifestyle.inspiration_style.value}")

    # --- Location ---
    lines.append("")
    lines.append("=== LOCATION ===")
    city = profile.location.city or "not set"
    country = profile.location.country or "not set"
    lines.append(f"City: {city}, Country: {country}")

    # --- Profile summary text (if present) ---
    if profile.profile_summary_text:
        lines.append("")
        lines.append("=== PROFILE SUMMARY ===")
        lines.append(profile.profile_summary_text)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: serialise query ontology
# ---------------------------------------------------------------------------

def _build_query_analysis(query: QueryOntology) -> str:
    """Serialise the QueryOntology into structured text for the LLM prompt."""
    lines: list[str] = []

    lines.append("=== QUERY ===")
    lines.append(f"Raw query: {query.raw_query}")
    lines.append(f"Mode: {query.mode.value}")
    lines.append(f"Complexity score: {query.query_complexity:.2f}")
    lines.append(f"Ambiguity score: {query.ambiguity_score:.2f}")

    if query.inferred_mood:
        lines.append(f"Inferred mood: {query.inferred_mood}")
    if query.inferred_urgency:
        lines.append(f"Inferred urgency: {query.inferred_urgency}")

    # Eat In attributes
    ea = query.eat_in_attributes
    if ea:
        lines.append("")
        lines.append("=== EAT IN ATTRIBUTES ===")
        lines.append(f"Desired cuisine: {ea.desired_cuisine or 'not specified'}")
        lines.append(f"Desired ingredients: {', '.join(ea.desired_ingredients) if ea.desired_ingredients else 'not specified'}")
        lines.append(f"Excluded ingredients: {', '.join(ea.excluded_ingredients) if ea.excluded_ingredients else 'none'}")
        lines.append(f"Time constraint: {f'{ea.time_constraint_minutes} min' if ea.time_constraint_minutes is not None else 'none'}")
        lines.append(f"Difficulty constraint: {ea.difficulty_constraint or 'none'}")
        lines.append(f"Mood: {ea.mood or 'not specified'}")
        lines.append(f"Occasion: {ea.occasion or 'not specified'}")
        lines.append(f"Nutritional goal: {ea.nutritional_goal or 'none'}")
        lines.append(f"Serving size: {ea.serving_size or 'not specified'}")

    # Conflicts
    if query.conflicts:
        lines.append("")
        lines.append("=== QUERY-PROFILE CONFLICTS ===")
        for conflict in query.conflicts:
            lines.append(
                f"[{conflict.conflict_type.value}] {conflict.description} "
                f"(resolution: {conflict.resolution_strategy.value})"
            )
            if conflict.warning_text:
                lines.append(f"  Warning: {conflict.warning_text}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: format full recipe data
# ---------------------------------------------------------------------------

def _build_recipe_data(ranked_recipes: list[dict], max_recipes: int = 5) -> str:
    """Format each recipe with ALL data, no truncation."""
    sections: list[str] = []

    for recipe in ranked_recipes[:max_recipes]:
        title = recipe.get("title_en") or recipe.get("title") or "Untitled Recipe"
        entity_id = recipe.get("_entity_id", "unknown")
        match_score = recipe.get("_match_score", 0.0)
        match_tier = recipe.get("_match_tier", "unknown")
        similarity = recipe.get("_similarity", 0.0)

        block: list[str] = [f"### {title}"]
        block.append(f"entity_id: {entity_id}")
        block.append(f"match_score: {match_score:.4f} | tier: {match_tier} | similarity: {similarity:.4f}")

        if recipe.get("description"):
            block.append(f"description: {recipe['description']}")
        if recipe.get("tips"):
            tips = recipe["tips"]
            if isinstance(tips, list):
                block.append(f"tips: {' | '.join(str(t) for t in tips)}")

        # --- Timing and logistics ---
        block.append(f"difficulty: {recipe.get('difficulty', 'unknown')}/5")
        block.append(f"time_total_min: {recipe.get('time_total_min', 'unknown')}")
        block.append(f"time_prep_min: {recipe.get('time_prep_min', 'unknown')}")
        block.append(f"time_cook_min: {recipe.get('time_cook_min', 'unknown')}")
        block.append(f"serves: {recipe.get('serves', 'unknown')}")

        # --- Tags ---
        for tag_key in ("cuisine_tags", "flavor_tags", "texture_tags", "season_tags", "occasion_tags", "dietary_tags"):
            tags = recipe.get(tag_key)
            if tags:
                block.append(f"{tag_key}: {', '.join(str(t) for t in tags)}")

        # --- Dietary flags ---
        dietary_flags = recipe.get("dietary_flags")
        if isinstance(dietary_flags, dict):
            active = [k for k, v in dietary_flags.items() if v is True]
            if active:
                block.append(f"dietary_flags: {', '.join(active)}")

        # --- Full ingredient list ---
        ingredients = recipe.get("ingredients") or []
        block.append(f"\nIngredients ({len(ingredients)}):")
        for ing in ingredients:
            if isinstance(ing, dict):
                name = ing.get("name", "")
                amount = ing.get("amount", "")
                unit = ing.get("unit", "")
                optional = ing.get("is_optional", False)
                parts = []
                if amount:
                    parts.append(str(amount))
                if unit:
                    parts.append(str(unit))
                parts.append(name)
                line = "- " + " ".join(p for p in parts if p)
                if optional:
                    line += " (optional)"
                block.append(line)
            else:
                block.append(f"- {ing}")

        # --- Full method steps ---
        steps = recipe.get("steps") or []
        block.append(f"\nMethod ({len(steps)} steps):")
        for step in steps:
            if isinstance(step, dict):
                num = step.get("step_number", "?")
                instruction = step.get("instruction", "")
                duration = step.get("duration_min")
                technique_tags = step.get("technique_tags") or []
                line = f"{num}. {instruction}"
                if duration:
                    line += f" [{duration} min]"
                if technique_tags:
                    line += f" (techniques: {', '.join(technique_tags)})"
                block.append(line)
            else:
                block.append(f"- {step}")

        # --- Nutrition ---
        nutr = recipe.get("nutrition_per_serving")
        block.append("\nNutrition per serving:")
        if isinstance(nutr, dict) and nutr:
            for key in ("kcal", "protein_g", "fat_g", "carbs_g", "fibre_g", "sugar_g", "salt_g"):
                val = nutr.get(key)
                if val is not None:
                    block.append(f"  {key}: {val}")
        else:
            block.append("  Not available in recipe data")

        # --- Factor scores ---
        factor_scores = recipe.get("_factor_scores")
        if isinstance(factor_scores, dict) and factor_scores:
            block.append("\nRanking factor scores:")
            for k, v in factor_scores.items():
                block.append(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

        sections.append("\n".join(block))

    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Deterministic fallback context builder
# ---------------------------------------------------------------------------

def _build_fallback_context(
    ranked_recipes: list[dict],
    query: QueryOntology,
    profile: UserProfile,
    retrieval_context: RetrievalContext,
) -> str:
    """Build a structured context deterministically when both LLM calls fail."""
    hard_stops = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    hard_stops_str = ", ".join(hard_stops) if hard_stops else "none"
    spectrum = profile.dietary.spectrum_label or "not specified"
    skill = profile.cooking.skill.value
    weeknight = profile.cooking.weeknight_minutes

    ea = query.eat_in_attributes
    cuisine_req = ea.desired_cuisine if ea else "not specified"
    time_req = f"{ea.time_constraint_minutes} min" if (ea and ea.time_constraint_minutes) else "none"
    mood_req = ea.mood if ea else "not specified"
    nutr_goal = ea.nutritional_goal if ea else "none"
    desired_ings = ", ".join(ea.desired_ingredients) if (ea and ea.desired_ingredients) else "not specified"

    recipe_data = _build_recipe_data(ranked_recipes)
    warnings_text = "\n".join(retrieval_context.warnings) if retrieval_context.warnings else "None"

    lines = [
        "[ONTOLOGY SUMMARY]",
        "Profile match factors:",
        f"- Dietary: {spectrum} | Hard stops: {hard_stops_str}",
        f"- Skill: {skill} | Time budget: weeknight {weeknight} min, weekend {profile.cooking.weekend_minutes} min",
        f"- Equipment: {profile.cooking.kitchen_setup.value}",
        "- Flavour sweet spots: not assessed (deterministic fallback)",
        "- Favourite ingredients: not assessed (deterministic fallback)",
        "- Cuisine affinities: not assessed (deterministic fallback)",
        "",
        "Query-specific factors:",
        f"- Desired cuisine: {cuisine_req}",
        f"- Desired ingredients: {desired_ings}",
        f"- Time constraint: {time_req}",
        f"- Mood / occasion: {mood_req}",
        f"- Nutritional goal: {nutr_goal}",
        "",
        "[ONTOLOGY DIRECTIVES]",
        f"Address: {query.raw_query}",
        f"Shape: Answer at {skill} level with practical detail",
        f"Respect: Hard dietary stops ({hard_stops_str}); time budget {weeknight} min on weeknights",
        "Weigh: Cuisine affinities, flavour preferences as available",
        "Avoid: Anything matching hard stops listed above",
        "",
        "[RECIPES & TECHNIQUES]",
        recipe_data,
        "",
        "[CAVEATS & GAPS]",
        "Ontology coverage:",
        "- Well matched: basic dietary and time constraints applied",
        "- Weak or missing: full profile analysis unavailable (deterministic fallback)",
        "",
        "Data quality:",
        f"- Retrieval warnings: {warnings_text}",
        "- [INFERRED] Full LLM-based curation unavailable due to service error",
        "",
        "Generation guidance:",
        "- Emphasise: dietary safety, time fit, practical cooking instructions",
        "- Caveat: profile analysis was limited; recommendations may not be fully personalised",
        "- Approach: Present recipes factually; note the limited personalisation",
    ]
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
        profile: UserProfile from Stage 0.
        retrieval_context: RetrievalContext from Stage 2b.

    Returns:
        A structured context string in the canonical section format.
    """
    if not ranked_recipes:
        logger.warning("Stage 5: No ranked recipes to refine — returning empty context")
        return (
            "[ONTOLOGY SUMMARY]\n"
            f"Profile match factors:\n"
            f"- Dietary: {profile.dietary.spectrum_label or 'not specified'} | Hard stops: "
            + ", ".join(r.label for r in profile.dietary.hard_stops if r.is_hard_stop)
            + "\n\n"
            "[ONTOLOGY DIRECTIVES]\n"
            f"Address: {query.raw_query}\n"
            "Respect: No recipes were retrieved — inform the user and suggest broadening the search.\n\n"
            "[RECIPES & TECHNIQUES]\n"
            "No matching recipes were found for this query.\n\n"
            "[CAVEATS & GAPS]\n"
            "Ontology coverage:\n"
            "- Well matched: n/a\n"
            "- Weak or missing: no candidates retrieved\n\n"
            "Generation guidance:\n"
            "- Approach: Acknowledge no strong matches. Suggest the user broaden their search or try a different query."
        )

    # Build input sections (deterministic — no LLM involved)
    profile_text = _build_profile_summary(profile)
    query_text = _build_query_analysis(query)
    recipe_text = _build_recipe_data(ranked_recipes)
    warnings_text = "\n".join(retrieval_context.warnings) if retrieval_context.warnings else "None"

    user_message = (
        f"USER PROFILE:\n{profile_text}\n\n"
        f"QUERY ANALYSIS:\n{query_text}\n\n"
        f"RETRIEVAL WARNINGS:\n{warnings_text}\n\n"
        f"RANKED RECIPE CANDIDATES ({min(len(ranked_recipes), 5)} of {len(ranked_recipes)}):\n"
        f"{recipe_text}\n\n"
        f"Produce the structured context document for the Response Generator. "
        f"Follow the output format exactly. Curate actively — assess each recipe "
        f"against the user profile, flag compliance issues, suggest adaptations, "
        f"and write actionable generation directives."
    )

    messages = [
        {"role": "system", "content": _REFINEMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # First LLM attempt
    try:
        refined_context = await call_llm(
            LLMOperation.REFINEMENT_AGENT,
            messages,
            max_tokens=2048,
        )

        if "[ONTOLOGY SUMMARY]" not in refined_context:
            logger.warning(
                "Refinement agent output missing [ONTOLOGY SUMMARY] — retrying with temperature=0"
            )
            raise ValueError("Missing expected section header in LLM output")

        logger.info(
            "Stage 5 complete: refined context length=%d chars",
            len(refined_context),
        )
        return refined_context

    except Exception as exc:
        logger.warning("Refinement LLM call failed (%s), retrying with temperature=0", exc)

        try:
            refined_context = await call_llm(
                LLMOperation.REFINEMENT_AGENT,
                messages,
                temperature=0,
                max_tokens=2048,
            )

            if "[ONTOLOGY SUMMARY]" not in refined_context:
                raise ValueError("Missing expected section header in retry output")

            logger.info(
                "Stage 5 complete (retry): refined context length=%d chars",
                len(refined_context),
            )
            return refined_context

        except Exception as exc2:
            logger.error(
                "Refinement retry also failed (%s) — falling back to deterministic context", exc2
            )
            return _build_fallback_context(ranked_recipes, query, profile, retrieval_context)
