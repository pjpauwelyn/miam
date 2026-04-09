"""
Stage 5: Refinement Agent (Experiment C)

THE MOST IMPORTANT PIPELINE RULE:
The generation agent (Stage 6) NEVER receives raw retrieved documents.
This agent produces the ONLY input to Stage 6.

EXPERIMENT C CHANGES vs main:
  - System prompt replaced: produces chain-of-thought <scratchpad> + structured
    XML document instead of prose sections.
  - Handoff format: <refinement> XML with sections:
      <scratchpad>        — visible CoT reasoning chain for Stage 6
      <ontology_summary>  — structured profile attributes
      <directives>        — imperative instructions for Stage 6
      <recipes>           — per-recipe blocks with compliance/skill/time/adaptations
      <gaps>              — quality flags and generation guidance
  - Each <recipe> has explicit child elements:
      <compliance_check status=PASS|WARN|FAIL reason="..." />
      <skill_fit status=GOOD|STRETCH reason="..." />
      <time_fit status=FITS|TIGHT|OVER delta_min="+/-x" />
      <adaptations><adaptation>...</adaptation></adaptations>
  - Validation: checks for <refinement> instead of [ONTOLOGY SUMMARY].
  - max_tokens increased from 2048 → 3072.
  - Fallback deterministic builder emits the same XML schema.

This is a drop-in replacement. Function signature UNCHANGED:
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
# System prompt (Experiment C: CoT scratchpad + XML handoff)
# ---------------------------------------------------------------------------

_REFINEMENT_SYSTEM_PROMPT = """\
You are the Refinement Agent of the miam food intelligence system.

Your output is the ONLY input the Response Generator (Stage 6) receives.

PROCESS — think step-by-step, then emit structured XML:

Step 1 (SCRATCHPAD): Reason through the query-profile fit internally.
  - Which recipes actually match the query intent?
  - Which dietary hard stops apply? Any violations?
  - Skill fit? Time fit? Cuisine match?
  - What adaptations would improve each recipe for this user?
  - What gaps exist in the candidates?

Step 2 (XML OUTPUT): Emit ONLY the XML document below. No prose before or after it.

RULES:
1. Dietary hard stops are absolute. Any recipe with a violation gets compliance status="FAIL".
2. Skill assessment: BEGINNER cannot execute advanced techniques without simplification.
3. EU/British English: aubergine, courgette, coriander, spring onion, hob.
4. All measurements metric. Temperatures in Celsius.
5. The <scratchpad> is visible to Stage 6 — use it to show your reasoning chain.
6. Every <recipe> must have <compliance_check>, <skill_fit>, <time_fit>, <adaptations>.
7. Every <recipe> must have at least one <adaptation> child element.
8. Output ONLY the XML document — no preamble, no sign-off.

OUTPUT FORMAT (reproduce XML structure exactly):

<refinement>
  <scratchpad>
    <query_intent>{what the user actually wants — 1 sentence}</query_intent>
    <profile_constraints>
      <hard_stops>{comma-separated list or "none"}</hard_stops>
      <skill_level>{level}</skill_level>
      <time_budget weeknight="{x}" weekend="{y}" />
      <flavor_preferences>{top 3 with scores}</flavor_preferences>
    </profile_constraints>
    <candidate_assessment>
      <candidate id="{entity_id}" title="{title}">
        <relevance>{HIGH|MEDIUM|LOW} — {1 sentence why}</relevance>
        <concerns>{specific issues or "none"}</concerns>
      </candidate>
    </candidate_assessment>
    <strategy>{1-2 sentences: which recipes to lead with, what to adapt, what to caveat}</strategy>
  </scratchpad>

  <ontology_summary>
    <dietary spectrum="{label}" hard_stops="{list}" />
    <cooking skill="{level}" weeknight_min="{x}" weekend_min="{y}" equipment="{key items}" />
    <flavors>{top preferences with scores}</flavors>
    <cuisine loves="{list}" avoids="{list}" />
  </ontology_summary>

  <directives>
    <address>{what to answer — concrete and direct}</address>
    <shape>{how to frame — skill-appropriate detail, tone, length}</shape>
    <respect>{absolute constraints}</respect>
    <weigh>{soft preferences}</weigh>
    <avoid>{things to skip}</avoid>
  </directives>

  <recipes>
    <recipe id="{entity_id}" title="{title}" score="{match_score}" tier="{tier}">
      <why>{1 sentence relevance rationale}</why>
      <ingredients count="{n}">
        <ingredient amount="{amount}" unit="{unit}" optional="{true|false}">{name}</ingredient>
      </ingredients>
      <method steps="{n}">
        <step n="{1}" duration_min="{x}" techniques="{tags}">{instruction}</step>
      </method>
      <tags>
        <flavors>{comma-separated}</flavors>
        <textures>{comma-separated}</textures>
        <cuisines>{comma-separated}</cuisines>
      </tags>
      <timing total="{x}" prep="{y}" cook="{z}" />
      <difficulty>{1-5}</difficulty>
      <serves>{n}</serves>
      <nutrition>
        <per_serving kcal="{v}" protein="{v}g" fat="{v}g" carbs="{v}g" fibre="{v}g" sugar="{v}g" salt="{v}g" />
      </nutrition>
      <compliance_check status="{PASS|WARN|FAIL}" reason="{specific reason}" />
      <skill_fit status="{GOOD|STRETCH}" reason="{specific reason}" />
      <time_fit status="{FITS|TIGHT|OVER}" delta_min="{+/- minutes}" />
      <adaptations>
        <adaptation>{specific, actionable suggestion for this user}</adaptation>
      </adaptations>
    </recipe>
  </recipes>

  <gaps>
    <well_matched>{attributes covered well}</well_matched>
    <weak_or_missing>{gaps in candidates}</weak_or_missing>
    <data_quality>{notes on missing/inferred data}</data_quality>
    <generation_guidance>
      <emphasise>{2-3 specific focus areas for Stage 6}</emphasise>
      <caveat>{1-2 things to qualify}</caveat>
      <approach>{1 sentence framing}</approach>
    </generation_guidance>
  </gaps>
</refinement>
"""

# ---------------------------------------------------------------------------
# Helper: serialise user profile (unchanged from main)
# ---------------------------------------------------------------------------

def _build_profile_summary(profile: UserProfile) -> str:
    """Serialise the complete UserProfile into structured text for the LLM prompt."""
    lines: list[str] = []

    lines.append("=== DIETARY IDENTITY ===")
    spectrum = profile.dietary.spectrum_label or "not specified"
    lines.append(f"Spectrum label: {spectrum}")

    hard_stops = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    lines.append(f"Hard stops: {', '.join(hard_stops) if hard_stops else 'none'}")

    soft_stops = [r.label for r in profile.dietary.soft_stops if not r.is_hard_stop]
    lines.append(f"Soft stops: {', '.join(soft_stops) if soft_stops else 'none'}")

    if profile.dietary.nuance_notes:
        lines.append(f"Nuance: {profile.dietary.nuance_notes}")

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

    lines.append("")
    lines.append("=== BUDGET ===")
    home_budget = f"\u20ac{profile.budget.home_per_meal_eur:.0f}" if profile.budget.home_per_meal_eur is not None else "not set"
    out_budget = f"\u20ac{profile.budget.out_per_meal_eur:.0f}" if profile.budget.out_per_meal_eur is not None else "not set"
    lines.append(f"Home per meal: {home_budget}")
    lines.append(f"Dining out per meal: {out_budget}")

    lines.append("")
    lines.append("=== ADVENTUROUSNESS ===")
    lines.append(f"Cooking: {profile.adventurousness.cooking_score:.1f}/10")
    lines.append(f"Dining: {profile.adventurousness.dining_score:.1f}/10")

    lines.append("")
    lines.append("=== NUTRITION AWARENESS ===")
    lines.append(f"Level: {profile.nutrition.level.value}")
    if profile.nutrition.tracked_dimensions:
        lines.append(f"Tracked: {', '.join(profile.nutrition.tracked_dimensions)}")

    lines.append("")
    lines.append("=== SOCIAL CONTEXT ===")
    lines.append(f"Default context: {profile.social.default_social_context.value}")
    lines.append(f"Meals out per week: {profile.social.meals_out_per_week}")
    lines.append(f"Home cooked per week: {profile.social.home_cooked_per_week}")

    lines.append("")
    lines.append("=== LIFESTYLE ===")
    lines.append(f"Seasonal preference: {profile.lifestyle.seasonal_preference_score:.1f}/10")
    lines.append(f"Sustainability priority: {profile.lifestyle.sustainability_priority_score:.1f}/10")
    if profile.lifestyle.special_interests:
        lines.append(f"Special interests: {', '.join(profile.lifestyle.special_interests)}")
    lines.append(f"Inspiration style: {profile.lifestyle.inspiration_style.value}")

    lines.append("")
    lines.append("=== LOCATION ===")
    city = profile.location.city or "not set"
    country = profile.location.country or "not set"
    lines.append(f"City: {city}, Country: {country}")

    if profile.profile_summary_text:
        lines.append("")
        lines.append("=== PROFILE SUMMARY ===")
        lines.append(profile.profile_summary_text)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: serialise query ontology (unchanged from main)
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
# Helper: format full recipe data (unchanged from main)
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

        block.append(f"difficulty: {recipe.get('difficulty', 'unknown')}/5")
        block.append(f"time_total_min: {recipe.get('time_total_min', 'unknown')}")
        block.append(f"time_prep_min: {recipe.get('time_prep_min', 'unknown')}")
        block.append(f"time_cook_min: {recipe.get('time_cook_min', 'unknown')}")
        block.append(f"serves: {recipe.get('serves', 'unknown')}")

        for tag_key in ("cuisine_tags", "flavor_tags", "texture_tags", "season_tags", "occasion_tags", "dietary_tags"):
            tags = recipe.get(tag_key)
            if tags:
                block.append(f"{tag_key}: {', '.join(str(t) for t in tags)}")

        dietary_flags = recipe.get("dietary_flags")
        if isinstance(dietary_flags, dict):
            active = [k for k, v in dietary_flags.items() if v is True]
            if active:
                block.append(f"dietary_flags: {', '.join(active)}")

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

        nutr = recipe.get("nutrition_per_serving")
        block.append("\nNutrition per serving:")
        if isinstance(nutr, dict) and nutr:
            for key in ("kcal", "protein_g", "fat_g", "carbs_g", "fibre_g", "sugar_g", "salt_g"):
                val = nutr.get(key)
                if val is not None:
                    block.append(f"  {key}: {val}")
        else:
            block.append("  Not available in recipe data")

        factor_scores = recipe.get("_factor_scores")
        if isinstance(factor_scores, dict) and factor_scores:
            block.append("\nRanking factor scores:")
            for k, v in factor_scores.items():
                block.append(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

        sections.append("\n".join(block))

    return "\n\n---\n\n".join(sections)


# ---------------------------------------------------------------------------
# Deterministic fallback (Experiment C: emits XML schema)
# ---------------------------------------------------------------------------

def _build_fallback_context(
    ranked_recipes: list[dict],
    query: QueryOntology,
    profile: UserProfile,
    retrieval_context: RetrievalContext,
) -> str:
    """Build a structured XML context deterministically when the LLM call fails."""
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

    warnings_text = "; ".join(retrieval_context.warnings) if retrieval_context.warnings else "none"

    # Build recipe XML blocks
    recipe_xml_parts = []
    for recipe in ranked_recipes[:5]:
        title = recipe.get("title_en") or recipe.get("title") or "Untitled"
        eid = recipe.get("_entity_id", "unknown")
        score = recipe.get("_match_score", 0.0)
        tier = recipe.get("_match_tier", "stretch_pick")
        recipe_xml_parts.append(
            f'    <recipe id="{eid}" title="{title}" score="{score:.4f}" tier="{tier}">\n'
            f'      <why>Deterministic fallback — no LLM curation available</why>\n'
            f'      <compliance_check status="UNKNOWN" reason="LLM unavailable" />\n'
            f'      <skill_fit status="UNKNOWN" reason="LLM unavailable" />\n'
            f'      <time_fit status="UNKNOWN" delta_min="0" />\n'
            f'      <adaptations>\n'
            f'        <adaptation>No adaptations available (fallback mode)</adaptation>\n'
            f'      </adaptations>\n'
            f'    </recipe>'
        )
    recipes_xml = "\n".join(recipe_xml_parts)

    return f"""<refinement>
  <scratchpad>
    <query_intent>{query.raw_query}</query_intent>
    <profile_constraints>
      <hard_stops>{hard_stops_str}</hard_stops>
      <skill_level>{skill}</skill_level>
      <time_budget weeknight="{weeknight}" weekend="{profile.cooking.weekend_minutes}" />
      <flavor_preferences>not assessed (deterministic fallback)</flavor_preferences>
    </profile_constraints>
    <candidate_assessment>No LLM assessment available (service error).</candidate_assessment>
    <strategy>Present recipes factually; note limited personalisation due to fallback mode.</strategy>
  </scratchpad>

  <ontology_summary>
    <dietary spectrum="{spectrum}" hard_stops="{hard_stops_str}" />
    <cooking skill="{skill}" weeknight_min="{weeknight}" weekend_min="{profile.cooking.weekend_minutes}" equipment="{profile.cooking.kitchen_setup.value}" />
    <flavors>not assessed</flavors>
    <cuisine loves="not assessed" avoids="not assessed" />
  </ontology_summary>

  <directives>
    <address>{query.raw_query}</address>
    <shape>Answer at {skill} level with practical detail</shape>
    <respect>Hard dietary stops ({hard_stops_str}); time budget {weeknight} min weeknights</respect>
    <weigh>Cuisine affinities, flavour preferences as available</weigh>
    <avoid>Anything matching hard stops</avoid>
  </directives>

  <recipes>
{recipes_xml}
  </recipes>

  <gaps>
    <well_matched>Basic dietary and time constraints applied</well_matched>
    <weak_or_missing>Full profile analysis unavailable (LLM service error — deterministic fallback)</weak_or_missing>
    <data_quality>Retrieval warnings: {warnings_text}. LLM-based curation unavailable.</data_quality>
    <generation_guidance>
      <emphasise>Dietary safety, time fit, practical cooking instructions</emphasise>
      <caveat>Profile analysis was limited; recommendations may not be fully personalised</caveat>
      <approach>Present recipes factually; note the limited personalisation</approach>
    </generation_guidance>
  </gaps>
</refinement>"""


# ---------------------------------------------------------------------------
# Main refinement function (signature unchanged)
# ---------------------------------------------------------------------------

async def refine_results(
    ranked_recipes: list[dict],
    query: QueryOntology,
    profile: UserProfile,
    retrieval_context: RetrievalContext,
) -> str:
    """
    Stage 5: Refinement Agent (Experiment C).

    Produces the structured XML context string that is the ONLY input to Stage 6.
    Format: <refinement> XML with CoT <scratchpad> + per-recipe compliance/adaptations.

    CRITICAL: This function is the information quality gate.
    Stage 6 (response_generator) sees nothing except what this function produces.

    Args:
        ranked_recipes: Top-ranked recipes from Stage 4 (with scoring metadata).
        query: QueryOntology from Stage 1+2.
        profile: UserProfile from Stage 0.
        retrieval_context: RetrievalContext from Stage 2b.

    Returns:
        A structured <refinement> XML string.
    """
    if not ranked_recipes:
        logger.warning("Stage 5: No ranked recipes to refine — returning empty XML context")
        hard_stops_str = ", ".join(
            r.label for r in profile.dietary.hard_stops if r.is_hard_stop
        ) or "none"
        return (
            "<refinement>\n"
            "  <scratchpad>\n"
            f"    <query_intent>{query.raw_query}</query_intent>\n"
            "    <strategy>No candidates were retrieved. Inform the user and suggest broadening the search.</strategy>\n"
            "  </scratchpad>\n"
            "  <ontology_summary>\n"
            f"    <dietary spectrum=\"{profile.dietary.spectrum_label or 'not specified'}\" hard_stops=\"{hard_stops_str}\" />\n"
            "  </ontology_summary>\n"
            "  <directives>\n"
            f"    <address>{query.raw_query}</address>\n"
            "    <respect>No recipes were retrieved — inform the user and suggest broadening the search.</respect>\n"
            "  </directives>\n"
            "  <recipes />\n"
            "  <gaps>\n"
            "    <well_matched>n/a</well_matched>\n"
            "    <weak_or_missing>No candidates retrieved</weak_or_missing>\n"
            "    <generation_guidance>\n"
            "      <approach>Acknowledge no strong matches. Suggest the user broaden their search or try a different query.</approach>\n"
            "    </generation_guidance>\n"
            "  </gaps>\n"
            "</refinement>"
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
        f"Produce the <refinement> XML document. Follow the output format exactly. "
        f"Start with the <scratchpad> reasoning chain, then emit the full XML. "
        f"Curate actively: assess each recipe against the user profile, flag compliance "
        f"issues with PASS/WARN/FAIL, assess skill and time fit, and write at least one "
        f"concrete adaptation per recipe."
    )

    messages = [
        {"role": "system", "content": _REFINEMENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        refined_context = await call_llm(
            LLMOperation.REFINEMENT_AGENT,
            messages,
            max_tokens=3072,  # increased from 2048 — XML + scratchpad is more verbose
        )
        logger.info(
            "Stage 5 (exp/c) complete: refined context length=%d chars",
            len(refined_context),
        )

        # Validate output has expected XML structure
        if "<refinement>" not in refined_context:
            logger.warning(
                "Refinement agent output missing <refinement> root element — falling back to deterministic"
            )
            return _build_fallback_context(ranked_recipes, query, profile, retrieval_context)

        return refined_context

    except Exception as exc:
        logger.error(
            "Stage 5 LLM call failed (%s) — falling back to deterministic XML context", exc
        )
        return _build_fallback_context(ranked_recipes, query, profile, retrieval_context)
