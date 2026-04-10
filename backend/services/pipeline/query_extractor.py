"""
Stage 1+2: Query Extractor

Converts a raw natural-language query + UserProfile into a fully-populated
QueryOntology using an LLM extraction pass followed by deterministic
logical-relationship enforcement.

Function signature:
    async def extract_query(raw_query: str, profile: UserProfile) -> QueryOntology
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from models.personal_ontology import (
    CookingSkill,
    DimensionWeight,
    PreferenceLevel,
    UserProfile,
)
from models.query_ontology import (
    ConflictResolution,
    ConflictType,
    EatInAttributes,
    LogicalRelationship,
    QueryAttribute,
    QueryMode,
    QueryOntology,
    QueryProfileConflict,
    RelationshipType,
    ValueType,
)
from services.llm_router import LLMOperation, call_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profile snapshot builder
# ---------------------------------------------------------------------------

def _build_profile_snapshot(profile: UserProfile) -> str:
    """
    Build a compact, token-efficient profile snapshot for the LLM prompt.
    Covers: summary, hard stops, loved cuisines, flavor extremes,
            cooking skill, and time budget.
    """
    lines: list[str] = []

    # Summary
    if profile.profile_summary_text:
        lines.append(f"User summary: {profile.profile_summary_text}")

    # Hard stops
    hard_stop_labels = [r.label for r in profile.dietary.hard_stops if r.is_hard_stop]
    if hard_stop_labels:
        lines.append(f"Hard stops (NEVER surface): {', '.join(hard_stop_labels)}")

    # Soft stops
    soft_stop_labels = [r.label for r in profile.dietary.soft_stops if not r.is_hard_stop]
    if soft_stop_labels:
        lines.append(f"Soft stops (avoid unless explicit): {', '.join(soft_stop_labels)}")

    # Dietary spectrum
    if profile.dietary.spectrum_label:
        lines.append(f"Dietary identity: {profile.dietary.spectrum_label}")

    # Loved cuisines
    loved = [
        a.cuisine for a in profile.cuisine_affinities.affinities
        if a.level in (PreferenceLevel.LOVE, PreferenceLevel.LIKE)
    ]
    if loved:
        lines.append(f"Loved cuisines: {', '.join(loved)}")

    disliked = [
        a.cuisine for a in profile.cuisine_affinities.affinities
        if a.level in (PreferenceLevel.DISLIKE, PreferenceLevel.NEVER)
    ]
    if disliked:
        lines.append(f"Disliked/never cuisines: {', '.join(disliked)}")

    # Flavor extremes (only those with strong signal, score <=2 or >=8)
    flavor = profile.flavor
    flavor_notes: list[str] = []
    flavor_map = {
        "spicy": flavor.spicy, "sweet": flavor.sweet, "sour": flavor.sour,
        "umami": flavor.umami, "bitter": flavor.bitter, "fatty": flavor.fatty,
        "fermented": flavor.fermented, "smoky": flavor.smoky, "salty": flavor.salty,
    }
    for dim, val in flavor_map.items():
        if val is not None:
            if val <= 2.0:
                flavor_notes.append(f"hates {dim}")
            elif val >= 8.0:
                flavor_notes.append(f"loves {dim}")
    if flavor_notes:
        lines.append(f"Flavor extremes: {', '.join(flavor_notes)}")

    # Cooking skill
    lines.append(f"Cooking skill: {profile.cooking.skill.value}")

    # Time budget
    lines.append(
        f"Time budget: weeknight <={profile.cooking.weeknight_minutes} min, "
        f"weekend <={profile.cooking.weekend_minutes} min"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are Agent B of the miam food intelligence system. Your role is to extract \
a structured QueryOntology from a natural-language food query, taking the \
user's personal profile into account.

RULES:
- Mode is always "eat_in" for this agent.
- Use EU/British English for all ingredient names \
  (aubergine, courgette, coriander, spring onion).
- All measurements metric.
- Extract only what is genuinely present or strongly implied; do not hallucinate.
- Detect conflicts between the query and the user's hard stops or soft stops.
- A hard-stop conflict always gets resolution "honor_profile".
- A soft-stop conflict gets resolution "show_warning" unless the user's query \
  is very explicit, in which case "honor_query".
- ambiguity_score: 0.0 = perfectly clear, 1.0 = completely ambiguous.
- query_complexity: 0.0 = single simple attribute, 1.0 = many interacting attributes.
- inferred_urgency: "quick" if time constraint or urgency language detected, \
  "relaxed" otherwise.

OUTPUT FORMAT (respond with ONLY valid JSON, no markdown, no prose):
{
  "mode": "eat_in",
  "eat_in_attributes": {
    "desired_cuisine": <string or null>,
    "desired_ingredients": [<string>, ...],
    "excluded_ingredients": [<string>, ...],
    "mood": <string or null>,
    "time_constraint_minutes": <int or null>,
    "difficulty_constraint": <"easy"|"medium"|"challenging"|null>,
    "nutritional_goal": <string or null>,
    "occasion": <string or null>,
    "serving_size": <int or null>
  },
  "extracted_attributes": [
    {
      "attribute": <string>,
      "value": <any>,
      "value_type": <"numeric"|"categorical"|"temporal"|"spatial"|"boolean"|"list">,
      "centrality": <float 0-1>,
      "description": <string or null>,
      "source_span": <string or null>
    }
  ],
  "conflicts": [
    {
      "conflict_type": <"dietary_violation"|"soft_stop_override"|"flavor_mismatch"|"time_exceeded"|"skill_mismatch">,
      "query_attribute": <string>,
      "profile_path": <string>,
      "query_value": <any>,
      "profile_value": <any>,
      "description": <string>,
      "resolution_strategy": <"honor_query"|"honor_profile"|"show_warning"|"ask_user">,
      "warning_text": <string or null>
    }
  ],
  "inferred_mood": <string or null>,
  "inferred_urgency": <"quick"|"relaxed"|null>,
  "query_complexity": <float 0-1>,
  "ambiguity_score": <float 0-1>
}

EXAMPLES:
Input: "quick pasta dinner"
Output: {"mode": "eat_in", "eat_in_attributes": {"desired_cuisine": "Italian", "desired_ingredients": ["pasta"], "time_constraint_minutes": 30, "difficulty_constraint": "easy", ...}, "inferred_urgency": "quick", "query_complexity": 0.2, "ambiguity_score": 0.1, "conflicts": [], ...}

Input: "gluten-free Thai curry, no shrimp, under 30 minutes"
Output: {"mode": "eat_in", "eat_in_attributes": {"desired_cuisine": "Thai", "desired_ingredients": ["curry paste"], "excluded_ingredients": ["shrimp"], "dietary_requirements": ["gluten_free"], "time_constraint_minutes": 30, ...}, "inferred_urgency": "quick", "query_complexity": 0.6, "ambiguity_score": 0.05, "conflicts": [], ...}

Input: "I want a steak" (user profile: vegetarian)
Output: {"mode": "eat_in", "eat_in_attributes": {"desired_ingredients": ["steak"], ...}, "conflicts": [{"conflict_type": "dietary_violation", "query_attribute": "desired_ingredients", "profile_path": "dietary.spectrum_label", "query_value": "steak", "profile_value": "vegetarian", "description": "User's profile indicates vegetarian but query requests steak", "resolution_strategy": "honor_profile", "warning_text": "Steak has been excluded due to your vegetarian profile."}], "query_complexity": 0.2, "ambiguity_score": 0.0, ...}
"""


# ---------------------------------------------------------------------------
# Deterministic post-LLM relationship rules
# ---------------------------------------------------------------------------

def _apply_logical_relationships(ontology: QueryOntology, profile: UserProfile) -> QueryOntology:
    """
    Apply deterministic logical relationship rules after LLM extraction.
    These rules encode culinary domain knowledge that should not depend on
    the LLM to reliably infer.
    """
    relationships: list[LogicalRelationship] = list(ontology.logical_relationships)
    ea = ontology.eat_in_attributes

    if ea is None:
        return ontology

    # Rule 1: time_constraint_minutes present -> urgency = "quick"
    if ea.time_constraint_minutes is not None and ea.time_constraint_minutes <= 30:
        if ontology.inferred_urgency != "quick":
            ontology.inferred_urgency = "quick"

    # Rule 2: occasion = "date night" IMPLIES mood in {romantic, special, indulgent}
    if ea.occasion and "date" in ea.occasion.lower():
        if not ontology.inferred_mood:
            ontology.inferred_mood = "romantic"
        relationships.append(LogicalRelationship(
            source_attribute="occasion",
            target_attribute="mood",
            relationship_type=RelationshipType.IMPLIES,
            logical_constraint="occasion=date night -> mood in {romantic, special, indulgent}",
            confidence=0.85,
        ))

    # Rule 3: difficulty_constraint=easy IMPLIES time_constraint is soft
    if ea.difficulty_constraint == "easy":
        relationships.append(LogicalRelationship(
            source_attribute="difficulty_constraint",
            target_attribute="time_constraint_minutes",
            relationship_type=RelationshipType.ATTENUATES,
            logical_constraint="difficulty=easy -> time constraint weight reduced",
            confidence=0.7,
        ))

    # Rule 4: high-spice cuisines with profile spicy <= 2 -> flavor_mismatch warning
    high_spice = {"thai", "sichuan", "korean", "indian", "ethiopian", "mexican"}
    if ea.desired_cuisine and ea.desired_cuisine.lower() in high_spice:
        if profile.flavor.spicy is not None and profile.flavor.spicy <= 2.0:
            already_flagged = any(
                c.conflict_type == ConflictType.FLAVOR_MISMATCH
                for c in ontology.conflicts
            )
            if not already_flagged:
                ontology.conflicts.append(QueryProfileConflict(
                    conflict_type=ConflictType.FLAVOR_MISMATCH,
                    query_attribute="desired_cuisine",
                    profile_path="flavor.spicy",
                    query_value=ea.desired_cuisine,
                    profile_value=profile.flavor.spicy,
                    description=(
                        f"Requested cuisine '{ea.desired_cuisine}' is typically spicy, "
                        f"but your spicy preference is very low ({profile.flavor.spicy}/10)."
                    ),
                    resolution_strategy=ConflictResolution.SHOW_WARNING,
                    warning_text=(
                        f"This cuisine is typically spicy. "
                        f"Recipes will be chosen for milder variants where possible."
                    ),
                ))

    # Rule 5: skill_mismatch - query implies "challenging" but skill is beginner/home_cook
    beginner_skills = {CookingSkill.BEGINNER, CookingSkill.HOME_COOK}
    if ea.difficulty_constraint == "challenging" and profile.cooking.skill in beginner_skills:
        already_flagged = any(
            c.conflict_type == ConflictType.SKILL_MISMATCH for c in ontology.conflicts
        )
        if not already_flagged:
            ontology.conflicts.append(QueryProfileConflict(
                conflict_type=ConflictType.SKILL_MISMATCH,
                query_attribute="difficulty_constraint",
                profile_path="cooking.skill",
                query_value="challenging",
                profile_value=profile.cooking.skill.value,
                description=(
                    f"Query requests challenging difficulty but skill level is "
                    f"'{profile.cooking.skill.value}'."
                ),
                resolution_strategy=ConflictResolution.SHOW_WARNING,
                warning_text="This recipe may be more challenging than your usual comfort zone.",
            ))

    # Rule 6: time_exceeded - query time_constraint exceeds profile weeknight budget
    # (only applies if query has a long time constraint - signals a weekend cook)
    if ea.time_constraint_minutes is not None:
        is_weekday = True  # conservative assumption
        profile_limit = profile.cooking.weeknight_minutes if is_weekday else profile.cooking.weekend_minutes
        if ea.time_constraint_minutes > profile_limit * 1.5:
            already_flagged = any(
                c.conflict_type == ConflictType.TIME_EXCEEDED for c in ontology.conflicts
            )
            if not already_flagged:
                ontology.conflicts.append(QueryProfileConflict(
                    conflict_type=ConflictType.TIME_EXCEEDED,
                    query_attribute="time_constraint_minutes",
                    profile_path="cooking.weeknight_minutes",
                    query_value=ea.time_constraint_minutes,
                    profile_value=profile_limit,
                    description=(
                        f"Requested time ({ea.time_constraint_minutes} min) significantly "
                        f"exceeds your typical time budget ({profile_limit} min)."
                    ),
                    resolution_strategy=ConflictResolution.SHOW_WARNING,
                    warning_text=f"This recipe takes longer than your usual time budget.",
                ))

    ontology.logical_relationships = relationships
    return ontology


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _bracket_count_json(text: str) -> str | None:
    """Extract the first complete JSON object from text using bracket counting.

    More robust than greedy regex when LLM outputs multiple JSON blocks or
    has prose before/after the object.
    """
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_json_from_text(text: str) -> dict:
    """Try to extract a JSON object from LLM response text.

    Strategy:
    1. Direct parse
    2. Markdown fence strip
    3. Bracket-counting extraction (primary)
    4. Greedy regex fallback
    """
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Bracket-counting extraction (handles multiple JSON blocks correctly)
    bracket_result = _bracket_count_json(text)
    if bracket_result is not None:
        try:
            return json.loads(bracket_result)
        except json.JSONDecodeError:
            pass

    # Greedy regex fallback
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

async def extract_query(raw_query: str, profile: UserProfile) -> QueryOntology:
    """
    Stage 1+2: Extract a QueryOntology from a raw natural-language query.

    Steps:
    1. Build a compact profile snapshot
    2. Call LLM (QUERY_EXTRACTION) to extract structured attributes
    3. Parse response into QueryOntology
    4. Apply deterministic logical relationship rules
    5. Fallback: return minimal QueryOntology on parse failure

    Args:
        raw_query: The user's raw input string.
        profile: The user's personal ontology.

    Returns:
        A populated QueryOntology instance.
    """
    profile_snapshot = _build_profile_snapshot(profile)

    user_message = (
        f"USER PROFILE:\n{profile_snapshot}\n\n"
        f"USER QUERY: {raw_query}"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # First attempt
    raw_response = ""
    try:
        raw_response = await call_llm(
            LLMOperation.QUERY_EXTRACTION,
            messages,
            max_tokens=1024,
        )
        parsed = _extract_json_from_text(raw_response)
    except Exception as exc:
        logger.warning(
            "Query extraction LLM call failed (%s), retrying with temperature=0", exc
        )
        try:
            raw_response = await call_llm(
                LLMOperation.QUERY_EXTRACTION,
                messages,
                temperature=0,
                max_tokens=1024,
            )
            parsed = _extract_json_from_text(raw_response)
        except Exception as exc2:
            logger.error(
                "Query extraction failed after retry (%s). Returning minimal ontology.", exc2
            )
            return QueryOntology(
                user_id=profile.user_id,
                raw_query=raw_query,
                mode=QueryMode.EAT_IN,
                eat_in_attributes=EatInAttributes(),
                query_complexity=0.5,
                ambiguity_score=0.8,
            )

    # Build QueryOntology from parsed dict
    try:
        ontology = _build_ontology_from_parsed(parsed, raw_query, profile)
    except Exception as exc:
        logger.error("Failed to build QueryOntology from parsed dict (%s). Minimal fallback.", exc)
        return QueryOntology(
            user_id=profile.user_id,
            raw_query=raw_query,
            mode=QueryMode.EAT_IN,
            eat_in_attributes=EatInAttributes(),
            query_complexity=0.5,
            ambiguity_score=0.8,
        )

    # Apply deterministic post-LLM rules
    ontology = _apply_logical_relationships(ontology, profile)

    return ontology


def _build_ontology_from_parsed(parsed: dict, raw_query: str, profile: UserProfile) -> QueryOntology:
    """Construct a QueryOntology from the LLM's parsed JSON output."""

    # --- EatInAttributes ---
    ea_raw = parsed.get("eat_in_attributes") or {}
    eat_in = EatInAttributes(
        desired_cuisine=ea_raw.get("desired_cuisine"),
        desired_ingredients=ea_raw.get("desired_ingredients") or [],
        excluded_ingredients=ea_raw.get("excluded_ingredients") or [],
        mood=ea_raw.get("mood"),
        time_constraint_minutes=ea_raw.get("time_constraint_minutes"),
        difficulty_constraint=ea_raw.get("difficulty_constraint"),
        nutritional_goal=ea_raw.get("nutritional_goal"),
        occasion=ea_raw.get("occasion"),
        serving_size=ea_raw.get("serving_size"),
    )

    # --- extracted_attributes ---
    extracted_attrs: list[QueryAttribute] = []
    for attr_raw in (parsed.get("extracted_attributes") or []):
        try:
            extracted_attrs.append(QueryAttribute(
                attribute=attr_raw["attribute"],
                value=attr_raw["value"],
                value_type=ValueType(attr_raw.get("value_type", "categorical")),
                centrality=float(attr_raw.get("centrality", 0.5)),
                description=attr_raw.get("description"),
                source_span=attr_raw.get("source_span"),
            ))
        except Exception:
            logger.debug("Skipping malformed extracted_attribute: %s", attr_raw)

    # --- conflicts ---
    conflicts: list[QueryProfileConflict] = []
    hard_stop_labels_lower = {r.label.lower() for r in profile.dietary.hard_stops if r.is_hard_stop}

    for c_raw in (parsed.get("conflicts") or []):
        try:
            ct_str = c_raw.get("conflict_type", "")
            try:
                ct = ConflictType(ct_str)
            except ValueError:
                ct = ConflictType.DIETARY_VIOLATION

            rs_str = c_raw.get("resolution_strategy", "show_warning")
            try:
                rs = ConflictResolution(rs_str)
            except ValueError:
                rs = ConflictResolution.SHOW_WARNING

            # Safety: any conflict involving a hard stop MUST be honor_profile
            qv = str(c_raw.get("query_value", "")).lower()
            if any(hs in qv for hs in hard_stop_labels_lower):
                ct = ConflictType.DIETARY_VIOLATION
                rs = ConflictResolution.HONOR_PROFILE

            conflicts.append(QueryProfileConflict(
                conflict_type=ct,
                query_attribute=c_raw.get("query_attribute", "unknown"),
                profile_path=c_raw.get("profile_path", "unknown"),
                query_value=c_raw.get("query_value"),
                profile_value=c_raw.get("profile_value"),
                description=c_raw.get("description", ""),
                resolution_strategy=rs,
                warning_text=c_raw.get("warning_text"),
            ))
        except Exception:
            logger.debug("Skipping malformed conflict: %s", c_raw)

    # --- Also check hard stops not caught by LLM ---
    # Use word-boundary regex to avoid false positives like "nuts" matching "doughnuts".
    all_query_ingredients = (
        eat_in.desired_ingredients
        + [eat_in.desired_cuisine or ""]
        + [raw_query.lower()]
    )
    query_text_lower = " ".join(all_query_ingredients).lower()

    for restriction in profile.dietary.hard_stops:
        if restriction.is_hard_stop and re.search(
            r"\b" + re.escape(restriction.label.lower()) + r"\b",
            query_text_lower,
        ):
            already = any(
                c.conflict_type == ConflictType.DIETARY_VIOLATION
                and re.search(
                    r"\b" + re.escape(restriction.label.lower()) + r"\b",
                    str(c.query_value or "").lower(),
                )
                for c in conflicts
            )
            if not already:
                conflicts.append(QueryProfileConflict(
                    conflict_type=ConflictType.DIETARY_VIOLATION,
                    query_attribute="desired_ingredients",
                    profile_path="dietary.hard_stops",
                    query_value=restriction.label,
                    profile_value=restriction.label,
                    description=(
                        f"Query implies '{restriction.label}' which is a hard dietary stop."
                    ),
                    resolution_strategy=ConflictResolution.HONOR_PROFILE,
                    warning_text=f"Recipes containing {restriction.label} have been excluded.",
                ))

    return QueryOntology(
        user_id=profile.user_id,
        raw_query=raw_query,
        mode=QueryMode.EAT_IN,
        eat_in_attributes=eat_in,
        extracted_attributes=extracted_attrs,
        conflicts=conflicts,
        inferred_mood=parsed.get("inferred_mood"),
        inferred_urgency=parsed.get("inferred_urgency"),
        query_complexity=float(parsed.get("query_complexity", 0.5)),
        ambiguity_score=float(parsed.get("ambiguity_score", 0.0)),
    )
