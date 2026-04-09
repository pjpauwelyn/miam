from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrievalContext:
    """
    Output of ontology fusion. Passed directly to the retrieval/ranking layer.
    """
    # Non-negotiable filters (hard stops + HONOR_PROFILE conflicts)
    hard_filters: list[dict]        = field(default_factory=list)

    # Soft filters: applied as scoring penalties, not strict exclusions
    soft_filters: list[dict]        = field(default_factory=list)

    # Weighted dimension map: {dimension_name: effective_weight (0–2.0)}
    scoring_vector: dict[str, float] = field(default_factory=dict)

    # Explicit value targets: {dimension_name: target_value}
    # Used when query specifies a concrete value (e.g. cuisine="Japanese")
    value_targets: dict[str, any]   = field(default_factory=dict)

    # User-facing warnings to display alongside results
    warnings: list[str]             = field(default_factory=list)

    # Whether retrieval should pause for user clarification
    requires_clarification: bool    = False
    clarification_question: Optional[str] = None

    # Debug trace for observability
    debug_trace: list[str]          = field(default_factory=list)
