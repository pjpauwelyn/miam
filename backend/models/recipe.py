"""Canonical RecipeDocument for MIAM's provenance-aware enrichment pipeline.

Field categories (see docs/SCHEMA_CONTRACT.md for full contract):
  CAT-A  source-preserved    (verbatim from origin, never overwritten)
  CAT-B  deterministic       (parsed / rule-derived, no LLM)
  CAT-C  externally-grounded (USDA / Open Food Facts nutrition)
  CAT-D  llm-inferred        (requires confidence + source tag)
  CAT-E  pipeline-meta       (tier, status, enrichment flags)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Provenance primitives
# ---------------------------------------------------------------------------

class EnrichmentSource(str, Enum):
    """Who/what produced a field value."""
    RECIPENLG_RAW    = "recipenlg_raw"      # verbatim from RecipeNLG dataset
    RULE_DETERMINISTIC = "rule_deterministic"  # regex / lookup-table
    USDA_FDC         = "usda_fdc"           # USDA FoodData Central API
    OPEN_FOOD_FACTS  = "open_food_facts"    # OFF API
    LLM_MISTRAL      = "llm_mistral"        # Mistral inference
    LLM_OPENAI       = "llm_openai"         # OpenAI inference
    MANUAL_CURATED   = "manual_curated"     # human editor
    UNKNOWN          = "unknown"


class FieldProvenance(BaseModel):
    """Attached to each enrichment group to record how it was produced."""
    source: EnrichmentSource = EnrichmentSource.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0,
        description="0=unknown/fabricated, 1=ground-truth verified")
    method: Optional[str] = Field(default=None,
        description="E.g. 'regex-unit-normaliser-v2', 'mistral-7b-instruct-q4'")
    enriched_at: Optional[datetime] = None

    @classmethod
    def raw(cls) -> FieldProvenance:
        return cls(source=EnrichmentSource.RECIPENLG_RAW, confidence=0.5,
                   enriched_at=datetime.now(timezone.utc))

    @classmethod
    def unknown(cls) -> FieldProvenance:
        return cls(source=EnrichmentSource.UNKNOWN, confidence=0.0)


# ---------------------------------------------------------------------------
# Enrichment status & tier
# ---------------------------------------------------------------------------

class EnrichmentStatus(str, Enum):
    """Pipeline stage gate for a recipe record."""
    RAW                   = "raw"
    PARSED                = "parsed"               # units normalised, steps split
    DETERMINISTIC_ENRICHED = "deterministic_enriched"  # dietary flags, cuisine lookup
    LLM_ENRICHED          = "llm_enriched"         # description, flavor, occasion
    VALIDATED             = "validated"             # passed Tier-1 criteria
    REJECTED              = "rejected"              # blocked from promotion


class TierLevel(int, Enum):
    """Quality tier. 0 = untiered, 1 = Tier-1 (RAG-ready)."""
    UNTIERED = 0
    TIER1    = 1   # trusted RAG context
    TIER2    = 2   # usable but incomplete
    TIER3    = 3   # skeleton / low-signal


class RecipeEnrichmentMeta(BaseModel):
    """Pipeline metadata block — CAT-E fields, stored as top-level columns in DB."""
    enrichment_status: EnrichmentStatus = EnrichmentStatus.RAW
    tier: TierLevel = TierLevel.UNTIERED
    tier_assigned_at: Optional[datetime] = None
    promotion_blocked_reason: Optional[str] = None

    # Boolean completion flags — fast filter without JSON traversal
    has_parsed_ingredients: bool = False
    has_normalised_units: bool = False
    has_dietary_flags: bool = False
    has_cuisine_tag: bool = False
    has_real_description: bool = False   # not a stub like "A recipe for..."
    has_llm_flavor_tags: bool = False
    has_nutrition: bool = False
    has_embedding: bool = False


# ---------------------------------------------------------------------------
# Sub-models (unchanged API surface)
# ---------------------------------------------------------------------------

class RecipeSubstitution(BaseModel):
    substitute: str
    ratio: str = Field(..., description="E.g. '1:1', '75% of original amount'")
    notes: str


class RecipeIngredient(BaseModel):
    name: str
    amount: float
    unit: str = Field(
        ...,
        description="g | ml | dl | cl | tbsp | tsp | piece | bunch | pinch | to-taste"
    )
    notes: Optional[str] = None
    is_optional: bool = False
    substitutions: list[RecipeSubstitution] = Field(default_factory=list)


class RecipeStep(BaseModel):
    step_number: int
    instruction: str
    duration_min: Optional[int] = None
    technique_tags: list[str] = Field(default_factory=list)


class DietaryFlags(BaseModel):
    is_vegan: bool = False
    is_vegetarian: bool = False
    is_pescatarian_ok: bool = False
    is_dairy_free: bool = False
    is_gluten_free: bool = False
    is_nut_free: bool = False
    is_halal_ok: bool = False
    contains_pork: bool = False
    contains_shellfish: bool = False
    contains_alcohol: bool = False
    vegan_if_substituted: bool = False
    gluten_free_if_substituted: bool = False


class NutritionPerServing(BaseModel):
    kcal: Optional[int] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    saturated_fat_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sugar_g: Optional[float] = None
    salt_g: Optional[float] = None


# ---------------------------------------------------------------------------
# Provenance companion blocks (one per field category)
# ---------------------------------------------------------------------------

class IngredientProvenance(BaseModel):
    """CAT-A / CAT-B provenance for ingredient parsing."""
    raw_text_source: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    unit_normalisation: FieldProvenance = Field(default_factory=FieldProvenance.unknown)


class IdentityProvenance(BaseModel):
    """Provenance for title, description, cuisine, region — CAT-A / CAT-D."""
    title: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    description: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    cuisine_tags: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    region_tag: FieldProvenance = Field(default_factory=FieldProvenance.unknown)


class SemanticProvenance(BaseModel):
    """Provenance for LLM-inferred semantic fields — CAT-D."""
    flavor_tags: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    texture_tags: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    occasion_tags: FieldProvenance = Field(default_factory=FieldProvenance.unknown)
    dietary_flags: FieldProvenance = Field(default_factory=FieldProvenance.unknown)


class NutritionProvenance(BaseModel):
    """Provenance for nutrition data — CAT-C preferred, CAT-D allowed with lower confidence."""
    nutrition_per_serving: FieldProvenance = Field(default_factory=FieldProvenance.unknown)


# ---------------------------------------------------------------------------
# Main canonical document
# ---------------------------------------------------------------------------

class RecipeDocument(BaseModel):
    """
    Canonical recipe document for MIAM's enrichment pipeline and RAG retrieval.

    Design principles:
    - Every enrichable field group has a parallel *_provenance companion.
    - The pipeline_meta block tracks status/tier/flags without polluting content fields.
    - Fields that are UNKNOWN must be left None / empty-list — never fabricated.
    - A recipe is Tier-1 eligible iff it passes the criteria in SCHEMA_CONTRACT.md.

    DB storage: content fields serialised into recipes_open.data (JSONB);
                pipeline_meta serialised into recipes_open.enrichment_flags;
                tier/enrichment_status stored as dedicated typed columns.
    """

    # ---- CAT-E: pipeline identity (always populated) -----------------------
    id: UUID = Field(default_factory=uuid4)
    pipeline_meta: RecipeEnrichmentMeta = Field(default_factory=RecipeEnrichmentMeta)

    # ---- CAT-A: source-preserved fields ------------------------------------
    # Written once from RecipeNLG, never overwritten by enrichment.
    title: str = Field(..., description="Title in original language, verbatim from source")
    source_dataset: str = Field(default="recipenlg",
        description="Dataset name: recipenlg | curated | open_food_facts")
    source_url: Optional[str] = Field(default=None,
        description="Original URL if available (RecipeNLG field: link)")
    raw_ingredients_text: list[str] = Field(default_factory=list,
        description="Verbatim ingredient strings from source — preserved for re-parsing")

    # ---- CAT-B: deterministic-derived fields -------------------------------
    # Populated by rule-based enrichment, no LLM needed.
    title_en: Optional[str] = Field(default=None,
        description="English title; None until translation stage")
    ingredients: list[RecipeIngredient] = Field(default_factory=list,
        description="Parsed and unit-normalised ingredients")
    steps: list[RecipeStep] = Field(default_factory=list)
    time_prep_min: Optional[int] = Field(default=None, ge=0)
    time_cook_min: Optional[int] = Field(default=None, ge=0)
    time_total_min: Optional[int] = Field(default=None, ge=0,
        description="Computed: prep + cook. None if either component is unknown.")
    serves: Optional[int] = Field(default=None, ge=1)
    dietary_flags: DietaryFlags = Field(default_factory=DietaryFlags,
        description="Deterministic flags derived from ingredient names")
    course_tags: list[str] = Field(default_factory=list)
    season_tags: list[str] = Field(default_factory=list)

    # ---- CAT-D: LLM-inferred fields ----------------------------------------
    # Only written after LLM enrichment. Left None/empty until then.
    description: Optional[str] = Field(default=None,
        description="100-200 words for European audience. None until LLM stage.")
    cuisine_tags: list[str] = Field(default_factory=list,
        description="Empty until cuisine enrichment stage")
    region_tag: Optional[str] = None
    flavor_tags: list[str] = Field(default_factory=list)
    texture_tags: list[str] = Field(default_factory=list)
    dietary_tags: list[str] = Field(default_factory=list,
        description="Human-readable dietary labels for display")
    difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    occasion_tags: list[str] = Field(default_factory=list)
    wine_pairing_notes: Optional[str] = None
    tips: list[str] = Field(default_factory=list)
    image_placeholder: Optional[str] = None

    # ---- CAT-C: externally-grounded nutrition ------------------------------
    # Populated by USDA/OFF lookup. Never fabricated by LLM.
    nutrition_per_serving: Optional[NutritionPerServing] = Field(
        default=None,
        description="Must be None if not externally grounded. Never LLM-fabricated."
    )

    # ---- Embedding ---------------------------------------------------------
    embedding_text: Optional[str] = Field(default=None,
        description="Pre-computed text for vector embedding. None until validated.")

    # ---- Provenance companions ---------------------------------------------
    identity_provenance: IdentityProvenance = Field(default_factory=IdentityProvenance)
    ingredient_provenance: IngredientProvenance = Field(default_factory=IngredientProvenance)
    semantic_provenance: SemanticProvenance = Field(default_factory=SemanticProvenance)
    nutrition_provenance: NutritionProvenance = Field(default_factory=NutritionProvenance)

    # ---- Metadata ----------------------------------------------------------
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Legacy field — retained for backward compat, derived from pipeline_meta
    @property
    def data_quality_score(self) -> float:
        tier_scores = {TierLevel.TIER1: 0.95, TierLevel.TIER2: 0.65,
                       TierLevel.TIER3: 0.35, TierLevel.UNTIERED: 0.1}
        return tier_scores.get(self.pipeline_meta.tier, 0.1)

    @property
    def source_type(self) -> str:
        """Legacy compat — maps to enrichment status."""
        if self.pipeline_meta.enrichment_status == EnrichmentStatus.VALIDATED:
            return "curated-verified"
        if self.pipeline_meta.enrichment_status in (
            EnrichmentStatus.LLM_ENRICHED, EnrichmentStatus.DETERMINISTIC_ENRICHED
        ):
            return "recipenlg_enriched"
        return "recipenlg_raw"

    @model_validator(mode="after")
    def _compute_total_time(self) -> RecipeDocument:
        if self.time_prep_min is not None and self.time_cook_min is not None:
            if self.time_total_min is None:
                object.__setattr__(self, "time_total_min",
                                   self.time_prep_min + self.time_cook_min)
        return self

    # -----------------------------------------------------------------------
    # Tier-1 eligibility check (mirrors DB tier_profile.py criteria)
    # -----------------------------------------------------------------------
    def tier1_eligible(self) -> tuple[bool, list[str]]:
        """Returns (eligible, list_of_failed_criteria)."""
        failures: list[str] = []

        if not self.title or len(self.title.strip()) < 3:
            failures.append("title: missing or too short")
        if not self.ingredients or len(self.ingredients) < 2:
            failures.append("ingredients: fewer than 2 parsed ingredients")
        if not self.steps or len(self.steps) < 2:
            failures.append("steps: fewer than 2 steps")
        if not self.description or len(self.description) < 50:
            failures.append("description: missing or stub (<50 chars)")
        if not self.cuisine_tags:
            failures.append("cuisine_tags: empty")
        if not self.course_tags:
            failures.append("course_tags: empty")
        if self.dietary_flags == DietaryFlags():  # all-False default = unenriched
            failures.append("dietary_flags: never enriched (all False may be correct, "
                            "but requires enrichment_status >= deterministic_enriched)")
        if self.pipeline_meta.enrichment_status == EnrichmentStatus.RAW:
            failures.append("enrichment_status: still raw")
        if (self.identity_provenance.description.confidence < 0.6
                and self.description is not None):
            failures.append("description.confidence < 0.6")

        return (len(failures) == 0, failures)
