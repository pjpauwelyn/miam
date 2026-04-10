"""
Stage 2b: Ontology Fusion

Pure Python, no LLM. Fuses the persistent UserProfile (PersonalOntology)
with the ephemeral QueryOntology to produce a RetrievalContext that drives
Stages 3-6.

Function signature:
    def fuse_ontologies(profile: UserProfile, query: QueryOntology) -> RetrievalContext

7-step fusion algorithm:
  Step 0: Hard stop safety gate
  Step 1: Build base weight vector from DimensionMeta
  Step 2: Query centrality modulation
  Step 3: Soft preference blending
  Step 4: Logical relationship enforcement
  Step 5: Context modulation (time of day, day of week, energy signal)
  Step 6: Conflict resolution pass
  Step 7: Assemble RetrievalContext
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Any

from models.fused_ontology import RetrievalContext
from models.personal_ontology import (
    CookingSkill,
    DimensionWeight,
    PreferenceLevel,
    UserProfile,
)
from models.query_ontology import (
    ConflictResolution,
    ConflictType,
    QueryOntology,
    RelationshipType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight map: DimensionWeight -> base retrieval multiplier
# ---------------------------------------------------------------------------
WEIGHT_MAP: dict[DimensionWeight, float] = {
    DimensionWeight.CORE:        1.0,
    DimensionWeight.IMPORTANT:   0.7,
    DimensionWeight.OPTIONAL:    0.3,
    DimensionWeight.CONTEXTUAL:  0.15,
}

# Skill -> numeric difficulty ceiling (recipe difficulty 1-5)
SKILL_DIFFICULTY_MAP: dict[CookingSkill, int] = {
    CookingSkill.BEGINNER:     1,
    CookingSkill.HOME_COOK:    2,
    CookingSkill.CONFIDENT:    3,
    CookingSkill.ADVANCED:     4,
    CookingSkill.PROFESSIONAL: 5,
}


# ---------------------------------------------------------------------------
# Context time helpers
# ---------------------------------------------------------------------------

def _now_in_tz(user_timezone: str = "UTC") -> datetime:
    """Return the current datetime in the given IANA timezone.

    Falls back to UTC if the timezone string is invalid.
    """
    try:
        tz = zoneinfo.ZoneInfo(user_timezone)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        logger.warning("Unknown timezone '%s', falling back to UTC", user_timezone)
        tz = zoneinfo.ZoneInfo("UTC")
    return datetime.now(tz)


def _is_weekend(user_timezone: str = "UTC") -> bool:
    """Return True if it is currently Saturday or Sunday in the user's timezone."""
    return _now_in_tz(user_timezone).weekday() >= 5  # 5=Saturday, 6=Sunday


# ---------------------------------------------------------------------------
# Main fusion function
# ---------------------------------------------------------------------------

def fuse_ontologies(profile: UserProfile, query: QueryOntology) -> RetrievalContext:
    """
    Fuse PersonalOntology + QueryOntology -> RetrievalContext.

    The RetrievalContext is the canonical input to Stage 3 (retriever)
    and Stage 4 (ranker). It encodes:
    - hard_filters: non-negotiable exclusion criteria
    - soft_filters: scoring penalties / preferences
    - scoring_vector: dimension weights for ranking
    - value_targets: concrete target values from the query
    - warnings: user-facing text
    - debug_trace: internal audit log
    """
    hard_filters: list[dict] = []
    soft_filters: list[dict] = []
    scoring_vector: dict[str, float] = {}
    value_targets: dict[str, Any] = {}
    warnings: list[str] = []
    debug_trace: list[str] = []

    # -----------------------------------------------------------------------
    # Step 0: Hard stop safety gate
    # -----------------------------------------------------------------------
    hard_stop_labels = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    for label in hard_stop_labels:
        hard_filters.append({
            "type": "exclude_ingredient",
            "value": label,
            "reason": "dietary_hard_stop",
        })
        debug_trace.append(f"Step0: hard stop -> exclude '{label}'")

    # Also add profile-level dietary flags from DietaryProfile.spectrum_label
    spectrum = (profile.dietary.spectrum_label or "").lower()
    if "vegan" in spectrum and "flexitarian" not in spectrum:
        hard_filters.append({"type": "dietary_flag", "value": "is_vegan", "required": True})
        debug_trace.append("Step0: vegan spectrum -> require is_vegan flag")
    elif "vegetarian" in spectrum:
        hard_filters.append({"type": "dietary_flag", "value": "is_vegetarian", "required": True})
        debug_trace.append("Step0: vegetarian spectrum -> require is_vegetarian flag")

    # Soft stops -> soft filter
    for restriction in profile.dietary.soft_stops:
        if not restriction.is_hard_stop:
            soft_filters.append({
                "type": "prefer_exclude_ingredient",
                "value": restriction.label,
                "penalty": 0.4,
            })
            debug_trace.append(f"Step0: soft stop -> prefer-exclude '{restriction.label}'")

    # -----------------------------------------------------------------------
    # Step 1: Build base weight vector from DimensionMeta
    # -----------------------------------------------------------------------
    def _base_weight(dim_weight: DimensionWeight) -> float:
        return WEIGHT_MAP.get(dim_weight, 0.3)

    scoring_vector["dietary"] = _base_weight(profile.dietary.meta.weight)
    scoring_vector["cuisine"] = _base_weight(profile.cuisine_affinities.meta.weight)
    scoring_vector["flavor"] = _base_weight(profile.flavor.meta.weight)
    scoring_vector["texture"] = _base_weight(profile.texture.meta.weight)
    scoring_vector["cooking_skill"] = _base_weight(profile.cooking.meta.weight)
    scoring_vector["nutrition"] = _base_weight(profile.nutrition.meta.weight)
    scoring_vector["adventurousness"] = _base_weight(profile.adventurousness.meta.weight)

    debug_trace.append(
        f"Step1: base scoring_vector = {scoring_vector}"
    )

    # -----------------------------------------------------------------------
    # Step 2: Query centrality modulation
    # -----------------------------------------------------------------------
    ea = query.eat_in_attributes
    if ea:
        # High-complexity queries amplify all signals proportionally
        complexity_boost = 1.0 + (query.query_complexity * 0.3)

        if ea.desired_cuisine:
            value_targets["cuisine"] = ea.desired_cuisine
            scoring_vector["cuisine"] = min(2.0, scoring_vector["cuisine"] * complexity_boost * 1.5)
            debug_trace.append(f"Step2: cuisine target='{ea.desired_cuisine}' -> weight boosted")

        if ea.desired_ingredients:
            value_targets["desired_ingredients"] = ea.desired_ingredients
            scoring_vector["ingredients"] = 1.2 * complexity_boost
            debug_trace.append(f"Step2: desired_ingredients={ea.desired_ingredients}")

        if ea.excluded_ingredients:
            for ing in ea.excluded_ingredients:
                hard_filters.append({
                    "type": "exclude_ingredient",
                    "value": ing,
                    "reason": "query_exclusion",
                })
            debug_trace.append(f"Step2: excluded_ingredients={ea.excluded_ingredients}")

        if ea.mood:
            value_targets["mood"] = ea.mood
            scoring_vector["occasion"] = 0.8
            debug_trace.append(f"Step2: mood='{ea.mood}'")

        if ea.time_constraint_minutes is not None:
            value_targets["max_time_min"] = ea.time_constraint_minutes
            hard_filters.append({
                "type": "max_time_min",
                "value": ea.time_constraint_minutes,
            })
            debug_trace.append(f"Step2: time constraint -> max_time_min={ea.time_constraint_minutes}")
        else:
            # Use profile time budget as soft filter
            soft_filters.append({
                "type": "prefer_max_time_min",
                "value": profile.cooking.weeknight_minutes,
                "penalty": 0.2,
            })
            debug_trace.append(f"Step2: profile weeknight budget -> soft max_time_min={profile.cooking.weeknight_minutes}")

        if ea.difficulty_constraint:
            value_targets["difficulty_constraint"] = ea.difficulty_constraint
            diff_map = {"easy": 2, "medium": 3, "challenging": 5}
            value_targets["max_difficulty"] = diff_map.get(ea.difficulty_constraint, 3)
            debug_trace.append(f"Step2: difficulty_constraint='{ea.difficulty_constraint}'")
        else:
            # Use profile skill as soft ceiling
            max_diff = SKILL_DIFFICULTY_MAP.get(profile.cooking.skill, 3)
            soft_filters.append({
                "type": "prefer_max_difficulty",
                "value": max_diff,
                "penalty": 0.3,
            })
            value_targets["profile_max_difficulty"] = max_diff
            debug_trace.append(f"Step2: profile skill -> soft max_difficulty={max_diff}")

        if ea.occasion:
            value_targets["occasion"] = ea.occasion
            debug_trace.append(f"Step2: occasion='{ea.occasion}'")

        if ea.nutritional_goal:
            value_targets["nutritional_goal"] = ea.nutritional_goal
            scoring_vector["nutrition"] = min(2.0, scoring_vector["nutrition"] * 2.0)
            debug_trace.append(f"Step2: nutritional_goal='{ea.nutritional_goal}' -> nutrition weight boosted")

    # For generic extracted_attributes - add to value_targets
    for attr in query.extracted_attributes:
        if attr.centrality >= 0.7 and attr.attribute not in value_targets:
            value_targets[f"query_{attr.attribute}"] = attr.value
            debug_trace.append(f"Step2: high-centrality attr '{attr.attribute}'={attr.value}")

    # -----------------------------------------------------------------------
    # Step 3: Soft preference blending
    # Query weight 0.7, profile weight 0.3
    # -----------------------------------------------------------------------
    # Cuisine affinity blending into scoring_vector
    cuisine_affinity_map: dict[str, float] = {}
    for aff in profile.cuisine_affinities.affinities:
        level_score = {
            PreferenceLevel.LOVE:    1.0,
            PreferenceLevel.LIKE:    0.7,
            PreferenceLevel.NEUTRAL: 0.5,
            PreferenceLevel.DISLIKE: 0.1,
            PreferenceLevel.NEVER:   0.0,
        }.get(aff.level, 0.5)
        cuisine_affinity_map[aff.cuisine.lower()] = level_score

    if cuisine_affinity_map:
        value_targets["cuisine_affinities"] = cuisine_affinity_map
        debug_trace.append(f"Step3: cuisine_affinities blended ({len(cuisine_affinity_map)} entries)")

    # Never cuisines -> hard filter, UNLESS the query explicitly requests that cuisine.
    # If the user says "I want Korean food" but Korean is in their never list,
    # we downgrade the hard filter to a soft filter (warning) and honor the query.
    # This only applies when the SPECIFIC cuisine name appears in query.cuisine_tags
    # (not for vague requests like "something Asian").
    query_cuisine_tags_lower: set[str] = set()
    if ea and ea.desired_cuisine:
        query_cuisine_tags_lower.add(ea.desired_cuisine.lower())
    # Also support explicit cuisine_tags field if present on the query model
    if hasattr(query, "cuisine_tags") and query.cuisine_tags:
        for ct in query.cuisine_tags:
            query_cuisine_tags_lower.add(ct.lower())

    never_cuisines = [
        aff.cuisine for aff in profile.cuisine_affinities.affinities
        if aff.level == PreferenceLevel.NEVER
    ]
    for cuisine in never_cuisines:
        cuisine_lower = cuisine.lower()
        if cuisine_lower in query_cuisine_tags_lower:
            # Query explicitly requests this cuisine -> downgrade hard filter to warning
            soft_filters.append({
                "type": "prefer_exclude_cuisine",
                "value": cuisine,
                "penalty": 0.2,
                "reason": "cuisine_never_overridden_by_query",
            })
            warnings.append(
                f"'{cuisine}' is in your never list, but you explicitly requested it. "
                f"Showing results with a caution note."
            )
            debug_trace.append(
                f"Step3: never cuisine '{cuisine}' overridden by explicit query request "
                f"-> downgraded to soft filter (strategy: honor_query)"
            )
        else:
            hard_filters.append({
                "type": "exclude_cuisine",
                "value": cuisine,
                "reason": "cuisine_never",
            })
            debug_trace.append(f"Step3: never cuisine -> exclude '{cuisine}'")

    # Disliked cuisines -> soft filter (unless query explicitly requests them)
    disliked_cuisines = [
        aff.cuisine for aff in profile.cuisine_affinities.affinities
        if aff.level == PreferenceLevel.DISLIKE
    ]
    query_cuisine = (ea.desired_cuisine or "").lower() if ea else ""
    for cuisine in disliked_cuisines:
        if cuisine.lower() != query_cuisine:
            soft_filters.append({
                "type": "prefer_exclude_cuisine",
                "value": cuisine,
                "penalty": 0.3,
            })

    # Flavor blending
    flavor_prefs: dict[str, float] = {}
    flavor_map = {
        "spicy": profile.flavor.spicy,
        "sweet": profile.flavor.sweet,
        "sour": profile.flavor.sour,
        "umami": profile.flavor.umami,
        "bitter": profile.flavor.bitter,
        "fatty": profile.flavor.fatty,
        "fermented": profile.flavor.fermented,
        "smoky": profile.flavor.smoky,
        "salty": profile.flavor.salty,
    }
    for dim, val in flavor_map.items():
        if val is not None:
            flavor_prefs[dim] = val / 10.0  # normalize to 0-1
    if flavor_prefs:
        value_targets["flavor_preferences"] = flavor_prefs
        debug_trace.append(f"Step3: flavor_preferences blended ({len(flavor_prefs)} dims)")

    # -----------------------------------------------------------------------
    # Step 4: Logical relationship enforcement
    # -----------------------------------------------------------------------
    for rel in query.logical_relationships:
        if rel.relationship_type == RelationshipType.REQUIRES:
            debug_trace.append(
                f"Step4: REQUIRES {rel.source_attribute} -> {rel.target_attribute}"
            )
        elif rel.relationship_type == RelationshipType.EXCLUDES:
            # Add to hard filters if not already present
            debug_trace.append(
                f"Step4: EXCLUDES {rel.source_attribute} -> {rel.target_attribute}"
            )
        elif rel.relationship_type == RelationshipType.AMPLIFIES:
            dim = rel.target_attribute
            if dim in scoring_vector:
                scoring_vector[dim] = min(2.0, scoring_vector[dim] * (1.0 + 0.3 * rel.confidence))
                debug_trace.append(f"Step4: AMPLIFIES {rel.target_attribute} -> weight={scoring_vector[dim]:.2f}")
        elif rel.relationship_type == RelationshipType.ATTENUATES:
            dim = rel.target_attribute
            if dim in scoring_vector:
                scoring_vector[dim] = max(0.0, scoring_vector[dim] * (1.0 - 0.2 * rel.confidence))
                debug_trace.append(f"Step4: ATTENUATES {rel.target_attribute} -> weight={scoring_vector[dim]:.2f}")

    # -----------------------------------------------------------------------
    # Step 5: Context modulation (time of day, day of week, energy signal)
    # user_timezone: not yet threaded through pipeline — defaulting to UTC.
    # TODO: wire user_timezone from profile.location or session context.
    # -----------------------------------------------------------------------
    user_timezone = "UTC"  # TODO: derive from profile.location.timezone when available
    session_ctx = query.session_context
    if session_ctx:
        tod = session_ctx.time_of_day
        dow = session_ctx.day_of_week
        energy = session_ctx.energy_signal

        # Morning / breakfast context -> boost light/quick recipes
        if tod in ("morning", "breakfast"):
            soft_filters.append({
                "type": "prefer_occasion_tag",
                "value": "breakfast",
                "boost": 0.3,
            })
            debug_trace.append("Step5: morning context -> boost breakfast occasions")

        # Dinner context -> standard
        if tod == "dinner":
            soft_filters.append({
                "type": "prefer_occasion_tag",
                "value": "dinner",
                "boost": 0.2,
            })

        # Weekend -> relax time constraint
        if dow == "weekend" and "prefer_max_time_min" in [f["type"] for f in soft_filters]:
            for sf in soft_filters:
                if sf["type"] == "prefer_max_time_min":
                    sf["value"] = profile.cooking.weekend_minutes
                    debug_trace.append(
                        f"Step5: weekend -> relaxed time to {profile.cooking.weekend_minutes} min"
                    )

        # Tired / low energy -> boost quick and easy
        if energy == "tired":
            if "max_time_min" not in value_targets:
                soft_filters.append({
                    "type": "prefer_max_time_min",
                    "value": 30,
                    "penalty": 0.3,
                })
                debug_trace.append("Step5: tired energy -> boost quick/easy recipes")

    else:
        # Infer from current time in the user's timezone
        now = datetime.now(timezone.utc)
        hour = now.hour
        if 5 <= hour < 10:
            soft_filters.append({"type": "prefer_occasion_tag", "value": "breakfast", "boost": 0.2})
            debug_trace.append("Step5: inferred morning from UTC time")
        elif 11 <= hour < 14:
            soft_filters.append({"type": "prefer_occasion_tag", "value": "lunch", "boost": 0.2})
            debug_trace.append("Step5: inferred lunch from UTC time")
        elif 17 <= hour < 22:
            soft_filters.append({"type": "prefer_occasion_tag", "value": "dinner", "boost": 0.2})
            debug_trace.append("Step5: inferred dinner from UTC time")

        if _is_weekend(user_timezone):
            for sf in soft_filters:
                if sf["type"] == "prefer_max_time_min":
                    sf["value"] = profile.cooking.weekend_minutes
                    debug_trace.append(f"Step5: inferred weekend -> relaxed time budget")

    # -----------------------------------------------------------------------
    # Step 6: Conflict resolution pass
    # -----------------------------------------------------------------------
    requires_clarification = False
    clarification_question: str | None = None

    for conflict in query.conflicts:
        rs = conflict.resolution_strategy

        if rs == ConflictResolution.HONOR_PROFILE:
            # Hard stop already in hard_filters from Step 0
            if conflict.conflict_type == ConflictType.DIETARY_VIOLATION:
                warnings.append(
                    f"Dietary restriction applied: {conflict.description}"
                )
            debug_trace.append(
                f"Step6: HONOR_PROFILE conflict -> hard filter enforced: {conflict.description}"
            )

        elif rs == ConflictResolution.HONOR_QUERY:
            # Remove any soft filter that contradicts the query intent
            debug_trace.append(
                f"Step6: HONOR_QUERY conflict -> profile preference overridden: {conflict.description}"
            )

        elif rs == ConflictResolution.SHOW_WARNING:
            if conflict.warning_text:
                warnings.append(conflict.warning_text)
            debug_trace.append(
                f"Step6: SHOW_WARNING -> added warning: {conflict.warning_text}"
            )

        elif rs == ConflictResolution.ASK_USER:
            requires_clarification = True
            clarification_question = (
                f"I noticed a conflict in your request: {conflict.description}. "
                f"How would you like me to handle it?"
            )
            debug_trace.append(
                f"Step6: ASK_USER -> clarification requested: {conflict.description}"
            )

    # Profile tensions -> warnings
    for tension in profile.tensions:
        if not tension.resolved:
            warnings.append(f"Profile note: {tension.description}")
            debug_trace.append(f"Step6: profile tension added to warnings")

    # -----------------------------------------------------------------------
    # Step 7: Assemble RetrievalContext
    # -----------------------------------------------------------------------
    debug_trace.append(
        f"Step7: assembled RetrievalContext — "
        f"hard_filters={len(hard_filters)}, soft_filters={len(soft_filters)}, "
        f"scoring_dims={len(scoring_vector)}, value_targets={list(value_targets.keys())}"
    )

    return RetrievalContext(
        hard_filters=hard_filters,
        soft_filters=soft_filters,
        scoring_vector=scoring_vector,
        value_targets=value_targets,
        warnings=warnings,
        requires_clarification=requires_clarification,
        clarification_question=clarification_question,
        debug_trace=debug_trace,
    )
