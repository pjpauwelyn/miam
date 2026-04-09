from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums specific to query ontology
# ---------------------------------------------------------------------------

class QueryMode(str, Enum):
    EAT_IN  = "eat_in"
    EAT_OUT = "eat_out"


class ValueType(str, Enum):
    NUMERIC     = "numeric"
    CATEGORICAL = "categorical"
    TEMPORAL    = "temporal"
    SPATIAL     = "spatial"
    BOOLEAN     = "boolean"
    LIST        = "list"


class RelationshipType(str, Enum):
    REQUIRES    = "requires"     # A is present → B must be present
    EXCLUDES    = "excludes"     # A is present → B must be absent
    AMPLIFIES   = "amplifies"    # A increases weight of B
    ATTENUATES  = "attenuates"   # A decreases weight of B
    IMPLIES     = "implies"      # A suggests B (soft version of REQUIRES)


class ConflictType(str, Enum):
    DIETARY_VIOLATION      = "dietary_violation"     # Query asks for a hard-stop item
    SOFT_STOP_OVERRIDE     = "soft_stop_override"    # Query asks for a soft-stop item
    FLAVOR_MISMATCH        = "flavor_mismatch"       # Query implies a disliked flavor profile
    BUDGET_EXCEEDED        = "budget_exceeded"       # Query implies higher price than profile budget
    TIME_EXCEEDED          = "time_exceeded"         # Query implies longer cook time than available
    SKILL_MISMATCH         = "skill_mismatch"        # Query implies technique above user skill level
    VIBE_MISMATCH          = "vibe_mismatch"         # Query vibe contradicts user vibe preferences
    CUISINE_DISLIKED       = "cuisine_disliked"      # Query requests a disliked cuisine
    LOCATION_OUT_OF_RANGE  = "location_out_of_range" # Query location beyond user radius


class ConflictResolution(str, Enum):
    HONOR_QUERY    = "honor_query"    # Query intent overrides profile preference
    HONOR_PROFILE  = "honor_profile"  # Profile preference overrides query (only for hard stops)
    SHOW_WARNING   = "show_warning"   # Surface result but add warning label
    ASK_USER       = "ask_user"       # Pause retrieval, ask for clarification


# ---------------------------------------------------------------------------
# Attribute-value pair (adapted from reference architecture)
# ---------------------------------------------------------------------------

class QueryAttribute(BaseModel):
    """
    A single extracted attribute from the user's query.
    Centrality (0–1) indicates how central this attribute is to the query's intent.
    An attribute with centrality=0.9 that can't be satisfied should block retrieval.
    An attribute with centrality=0.2 can be ignored if it reduces result set too much.
    """
    attribute:   str  = Field(..., description="Semantic attribute name, e.g. 'desired_cuisine', 'mood'")
    value:       Any  = Field(..., description="Extracted value — type depends on value_type")
    value_type:  ValueType = Field(default=ValueType.CATEGORICAL)
    centrality:  float = Field(default=0.5, ge=0.0, le=1.0, description="How central to query intent (0=peripheral, 1=core)")
    description: Optional[str] = Field(default=None, description="Explanation of why this was extracted")
    source_span: Optional[str] = Field(default=None, description="The substring of the query that implied this attribute")

    # Constraints on value (e.g. for numeric: min/max, for categorical: allowed values)
    constraints: Optional[dict[str, Any]] = Field(default=None)


# ---------------------------------------------------------------------------
# Logical relationship between attributes
# ---------------------------------------------------------------------------

class LogicalRelationship(BaseModel):
    """
    Expresses a semantic dependency between two extracted query attributes.
    E.g.: occasion=romantic REQUIRES vibe=intimate
          price_sensitivity=budget EXCLUDES cuisine=omakase
    """
    source_attribute: str = Field(..., description="Attribute name (must exist in extracted_attributes)")
    target_attribute: str = Field(..., description="Attribute name (must exist in extracted_attributes)")
    relationship_type: RelationshipType
    logical_constraint: Optional[str] = Field(
        default=None,
        description="Human-readable constraint expression, e.g. 'occasion=romantic → vibe ∈ {intimate, cozy, romantic}'"
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Conflict between query intent and personal profile
# ---------------------------------------------------------------------------

class QueryProfileConflict(BaseModel):
    """
    A detected conflict between what the user asked for and their personal ontology.
    Stored with a resolution strategy so the fusion layer knows how to handle it.
    """
    conflict_type:       ConflictType
    query_attribute:     str  = Field(..., description="Which query attribute triggered the conflict")
    profile_path:        str  = Field(..., description="Dotted path to the conflicting profile value")
    query_value:         Any
    profile_value:       Any
    description:         str  = Field(..., description="Human-readable explanation")
    resolution_strategy: ConflictResolution
    warning_text:        Optional[str] = Field(
        default=None,
        description="If resolution=SHOW_WARNING, this text is shown to the user alongside results"
    )


# ---------------------------------------------------------------------------
# Eat In specific attributes
# ---------------------------------------------------------------------------

class EatInAttributes(BaseModel):
    """
    Structured extraction for Eat In queries.
    All fields optional — only populated when present in the query.
    """
    desired_cuisine:       Optional[str]       = None
    desired_ingredients:   list[str]           = Field(default_factory=list)
    excluded_ingredients:  list[str]           = Field(default_factory=list)
    mood:                  Optional[str]       = None   # e.g. "comforting", "light", "celebratory"
    time_constraint_minutes: Optional[int]    = None
    difficulty_constraint: Optional[str]      = None   # "easy", "medium", "challenging"
    nutritional_goal:      Optional[str]      = None   # e.g. "high protein", "low carb"
    occasion:              Optional[str]      = None   # "weeknight dinner", "date night at home", "meal prep"
    serving_size:          Optional[int]      = None   # number of servings


class EatOutAttributes(BaseModel):
    """
    Structured extraction for Eat Out queries.
    All fields optional — only populated when present in the query.
    """
    desired_cuisine:      Optional[str]  = None
    desired_vibe:         Optional[str]  = None
    location_city:        Optional[str]  = None
    location_neighborhood: Optional[str] = None
    occasion:             Optional[str]  = None
    group_size:           Optional[int]  = None
    price_sensitivity:    Optional[str]  = None  # "budget", "mid-range", "splurge"
    specific_requirements: list[str]    = Field(default_factory=list)
    # e.g. ["terrace", "private room", "live music", "dog-friendly"]
    open_now:             Optional[bool] = None
    booking_required:     Optional[bool] = None


# ---------------------------------------------------------------------------
# Session context (lightweight, per-session, not persisted to profile)
# ---------------------------------------------------------------------------

class SessionContext(BaseModel):
    """
    Ephemeral context signals that modulate retrieval for this session only.
    Not persisted to the UserProfile.
    """
    time_of_day:        Optional[str]      = None  # "morning", "lunch", "afternoon", "dinner", "late_night"
    day_of_week:        Optional[str]      = None  # "weekday", "weekend"
    recent_query_types: list[str]          = Field(default_factory=list)
    # e.g. ["eat_out", "eat_out", "eat_in"] — last 3 queries
    recent_rejections:  list[str]          = Field(default_factory=list)
    # Cuisine/dish types rejected in this session
    energy_signal:      Optional[str]      = None
    # "tired" (inferred from "quick", "easy", "simple" language) or "adventurous"


# ---------------------------------------------------------------------------
# Root Query Ontology model
# ---------------------------------------------------------------------------

class QueryOntology(BaseModel):
    """
    Per-query dynamic semantic representation.
    Created fresh for every user query. Ephemeral (not persisted long-term).
    """
    query_id:   UUID    = Field(default_factory=uuid4)
    user_id:    UUID    = Field(..., description="Reference to the UserProfile")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Raw input
    raw_query:  str = Field(..., description="Exact text the user submitted")
    mode:       QueryMode

    # Structured extraction
    eat_in_attributes:  Optional[EatInAttributes]  = None
    eat_out_attributes: Optional[EatOutAttributes] = None

    # Generic attribute-value pairs (covers dimensions not in structured fields)
    extracted_attributes: list[QueryAttribute] = Field(default_factory=list)

    # Semantic relationships between extracted attributes
    logical_relationships: list[LogicalRelationship] = Field(default_factory=list)

    # Conflicts with user profile
    conflicts: list[QueryProfileConflict] = Field(default_factory=list)

    # Derived signals
    inferred_mood:         Optional[str]  = None
    inferred_urgency:      Optional[str]  = None  # "relaxed", "quick", "urgent"
    query_complexity:      float          = Field(default=0.5, ge=0.0, le=1.0,
                                                  description="How complex/multi-dimensional this query is")
    ambiguity_score:       float          = Field(default=0.0, ge=0.0, le=1.0,
                                                  description="How ambiguous the query is (high = consider asking for clarification)")

    # Session context
    session_context:       Optional[SessionContext] = None

    @model_validator(mode="after")
    def validate_mode_attributes(self) -> "QueryOntology":
        """Ensure the correct mode-specific attribute block is populated."""
        if self.mode == QueryMode.EAT_IN and self.eat_in_attributes is None:
            self.eat_in_attributes = EatInAttributes()
        if self.mode == QueryMode.EAT_OUT and self.eat_out_attributes is None:
            self.eat_out_attributes = EatOutAttributes()
        return self

    def has_hard_stop_conflict(self) -> bool:
        """Returns True if any conflict involves a dietary hard stop violation."""
        return any(c.conflict_type == ConflictType.DIETARY_VIOLATION for c in self.conflicts)

    def get_blocking_conflicts(self) -> list[QueryProfileConflict]:
        """Returns conflicts that should block retrieval (HONOR_PROFILE or hard stops)."""
        return [c for c in self.conflicts if c.resolution_strategy == ConflictResolution.HONOR_PROFILE]

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat(), UUID: str}
