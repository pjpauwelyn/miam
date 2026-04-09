from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Foundational enums and building blocks
# ---------------------------------------------------------------------------

class DimensionWeight(str, Enum):
    """How strongly a dimension influences retrieval and ranking."""
    CORE        = "core"        # Always applied; failure to match is disqualifying
    IMPORTANT   = "important"   # Strongly down-ranks mismatches
    OPTIONAL    = "optional"    # Mild signal; used for tie-breaking
    CONTEXTUAL  = "contextual"  # Only applied in specific query contexts


class UpdateSource(str, Enum):
    ONBOARDING   = "onboarding"    # Explicit answer during onboarding interview
    BEHAVIOR     = "behavior"      # Inferred from clicks, skips, saves
    FEEDBACK     = "feedback"      # Explicit rating or rejection after interaction
    DIRECT_EDIT  = "direct_edit"   # User updated their profile manually
    INFERENCE    = "inference"     # LLM-inferred from free-text during conversation


class CookingSkill(str, Enum):
    BEGINNER     = "beginner"
    HOME_COOK    = "home_cook"
    CONFIDENT    = "confident"
    ADVANCED     = "advanced"
    PROFESSIONAL = "professional"


class KitchenSetup(str, Enum):
    BASIC         = "basic"          # Stovetop, oven, basic utensils
    WELL_EQUIPPED = "well_equipped"  # Above + blender, stand mixer, etc.
    FULLY_EQUIPPED = "fully_equipped" # Above + sous vide, pressure cooker, etc.


class NutritionalAwarenessLevel(str, Enum):
    NONE     = "none"
    LIGHT    = "light"     # Occasional tracking / light calorie awareness
    MODERATE = "moderate"  # Tracks macros or specific nutrients
    STRICT   = "strict"    # Medical diet, sports nutrition, detailed tracking


class SocialContext(str, Enum):
    SOLO   = "solo"
    COUPLE = "couple"
    FAMILY = "family"
    GROUP  = "group"


class InspirationStyle(str, Enum):
    ONE_BEST       = "one_best"       # Give me your single best recommendation
    SHORT_LIST     = "short_list"     # Give me 3–5 options
    WIDE_SELECTION = "wide_selection" # Show me everything relevant


class PreferenceLevel(str, Enum):
    """Discrete preference levels for cuisine / vibe affinities."""
    LOVE    = "love"
    LIKE    = "like"
    NEUTRAL = "neutral"
    DISLIKE = "dislike"
    NEVER   = "never"    # Hard-stop equivalent for a category


class TensionSeverity(str, Enum):
    LOW    = "low"     # Minor inconsistency, still workable
    MEDIUM = "medium"  # Retrievable but query-time warning needed
    HIGH   = "high"    # Likely to produce bad results; needs user resolution


# ---------------------------------------------------------------------------
# Dimension metadata wrapper
# ---------------------------------------------------------------------------

class DimensionMeta(BaseModel):
    """
    Wraps every significant dimension with operational metadata.
    Attached to top-level sub-models via composition, not inheritance,
    so schema complexity stays local.
    """
    weight:        DimensionWeight = Field(
        ...,
        description="Retrieval influence level of this dimension"
    )
    confidence:    float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description=(
            "System confidence in this value. "
            "1.0 = user stated explicitly; 0.0 = pure guess. "
            "Values below 0.4 are treated as tentative and shown "
            "with a 'confirm this?' prompt at next interaction."
        )
    )
    last_updated:  datetime = Field(default_factory=datetime.utcnow)
    update_source: UpdateSource = Field(default=UpdateSource.ONBOARDING)


# ---------------------------------------------------------------------------
# Dietary profile
# ---------------------------------------------------------------------------

class DietaryRestriction(BaseModel):
    """
    A single dietary restriction. Hard stops are absolute (allergy, ethical,
    religious). Soft stops are preferred avoidances that can be overridden
    by an explicit query.
    """
    label: str = Field(..., description="E.g. 'gluten', 'shellfish', 'pork', 'dairy'")
    is_hard_stop: bool = Field(
        ...,
        description=(
            "True = never surface in results, regardless of query. "
            "False = down-rank but can be unlocked by explicit query intent."
        )
    )
    reason: Optional[str] = Field(
        default=None,
        description="Optional: 'allergy', 'religious', 'ethical', 'intolerance', 'preference'"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class DietaryProfile(BaseModel):
    """
    Dietary identity modeled as a spectrum rather than binary flags.
    A user can have a 'flexitarian' label (spectrum_label) while also having
    specific hard stops (e.g. no red meat) and soft stops (e.g. prefer to
    avoid factory-farmed chicken).
    """
    spectrum_label: Optional[str] = Field(
        default=None,
        description=(
            "Free-text dietary identity: 'vegan', 'vegetarian', "
            "'pescatarian', 'flexitarian', 'omnivore', "
            "'pescatarian-leaning vegan', etc. "
            "This is a self-reported label, not a constraint engine — "
            "constraints come from hard_stops and soft_stops."
        )
    )
    hard_stops: list[DietaryRestriction] = Field(
        default_factory=list,
        description="Absolute dietary restrictions. Never overridden."
    )
    soft_stops: list[DietaryRestriction] = Field(
        default_factory=list,
        description="Preferred avoidances. Can be overridden by explicit query."
    )
    nuance_notes: Optional[str] = Field(
        default=None,
        description=(
            "Free-text nuance that structured fields can't capture. "
            "E.g. 'vegan except for occasional sushi', "
            "'no red meat but yes to prosciutto on pizza'."
        )
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.CORE, confidence=0.9)
    )


# ---------------------------------------------------------------------------
# Cuisine affinities
# ---------------------------------------------------------------------------

class CuisineAffinity(BaseModel):
    """
    Per-cuisine preference with optional sub-nuance.
    The sub_nuances field captures ingredient-level or technique-level
    exceptions within a cuisine.
    """
    cuisine: str = Field(..., description="E.g. 'Thai', 'Japanese', 'Mexican', 'French'")
    level: PreferenceLevel = Field(default=PreferenceLevel.NEUTRAL)
    sub_nuances: list[str] = Field(
        default_factory=list,
        description=(
            "Ingredient or technique exceptions within this cuisine. "
            "E.g. ['love pad thai', 'hate fish sauce', 'avoid nam prik dishes']. "
            "Used as boosting/filtering signals at the dish level."
        )
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class CuisineAffinityProfile(BaseModel):
    affinities: list[CuisineAffinity] = Field(default_factory=list)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.IMPORTANT, confidence=0.5)
    )


# ---------------------------------------------------------------------------
# Flavor profile
# ---------------------------------------------------------------------------

class FlavorProfile(BaseModel):
    """
    Numeric preference scores per flavor dimension (0 = strong dislike, 10 = strong preference).
    5 = neutral / no strong feeling.
    None = not yet known.
    """
    spicy:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    sweet:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    sour:      Optional[float] = Field(default=None, ge=0.0, le=10.0)
    umami:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    bitter:    Optional[float] = Field(default=None, ge=0.0, le=10.0)
    fatty:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    fermented: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    smoky:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    salty:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.IMPORTANT, confidence=0.4)
    )


# ---------------------------------------------------------------------------
# Texture preferences
# ---------------------------------------------------------------------------

class TextureProfile(BaseModel):
    """
    Numeric preference scores per texture dimension (0–10).
    None = not yet known.
    """
    crunchy:  Optional[float] = Field(default=None, ge=0.0, le=10.0)
    creamy:   Optional[float] = Field(default=None, ge=0.0, le=10.0)
    soft:     Optional[float] = Field(default=None, ge=0.0, le=10.0)
    chewy:    Optional[float] = Field(default=None, ge=0.0, le=10.0)
    crispy:   Optional[float] = Field(default=None, ge=0.0, le=10.0)
    silky:    Optional[float] = Field(default=None, ge=0.0, le=10.0)
    chunky:   Optional[float] = Field(default=None, ge=0.0, le=10.0)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.OPTIONAL, confidence=0.3)
    )


# ---------------------------------------------------------------------------
# Cooking context
# ---------------------------------------------------------------------------

class KitchenEquipment(BaseModel):
    """
    Specific equipment flags beyond the baseline KitchenSetup enum.
    Only flagged True if user confirmed they have it.
    """
    stand_mixer:     bool = False
    food_processor:  bool = False
    sous_vide:       bool = False
    pressure_cooker: bool = False
    air_fryer:       bool = False
    wok:             bool = False
    cast_iron:       bool = False
    outdoor_grill:   bool = False
    pasta_machine:   bool = False
    dehydrator:      bool = False
    # Extend freely — new fields default to False and won't break old profiles


class CookingContext(BaseModel):
    skill:             CookingSkill  = Field(default=CookingSkill.HOME_COOK)
    kitchen_setup:     KitchenSetup  = Field(default=KitchenSetup.WELL_EQUIPPED)
    specific_equipment: KitchenEquipment = Field(default_factory=KitchenEquipment)
    weeknight_minutes: int = Field(
        default=30, ge=0,
        description="Max cooking time on weeknights (minutes)"
    )
    weekend_minutes:   int = Field(
        default=90, ge=0,
        description="Max cooking time on weekends (minutes)"
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.CORE, confidence=0.7)
    )


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class BudgetProfile(BaseModel):
    home_per_meal_eur: Optional[float] = Field(
        default=None, ge=0.0,
        description="Target ingredient cost per home meal (EUR)"
    )
    out_per_meal_eur: Optional[float] = Field(
        default=None, ge=0.0,
        description="Comfortable spend per person when dining out (EUR)"
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.IMPORTANT, confidence=0.5)
    )


# ---------------------------------------------------------------------------
# Dining vibe affinities
# ---------------------------------------------------------------------------

class VibeAffinity(BaseModel):
    vibe: str = Field(..., description="E.g. 'cozy', 'lively', 'trendy', 'classic'")
    score: float = Field(default=5.0, ge=0.0, le=10.0)
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)


class DiningVibeProfile(BaseModel):
    """
    Per-vibe preference scores. Standard vibes pre-populated at score=5.
    Custom vibes can be added to the list.
    """
    vibes: list[VibeAffinity] = Field(
        default_factory=lambda: [
            VibeAffinity(vibe="cozy",       score=5.0),
            VibeAffinity(vibe="lively",     score=5.0),
            VibeAffinity(vibe="trendy",     score=5.0),
            VibeAffinity(vibe="classic",    score=5.0),
            VibeAffinity(vibe="hidden_gem", score=5.0),
            VibeAffinity(vibe="romantic",   score=5.0),
            VibeAffinity(vibe="business",   score=5.0),
        ]
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.IMPORTANT, confidence=0.4)
    )


# ---------------------------------------------------------------------------
# Adventurousness
# ---------------------------------------------------------------------------

class AdventurousnessProfile(BaseModel):
    """
    Separate scores for cooking adventurousness (trying new techniques/ingredients)
    and dining adventurousness (trying unfamiliar restaurants/cuisines).
    Decoupled because many people are adventurous diners but conservative cooks.
    """
    cooking_score: float = Field(
        default=5.0, ge=0.0, le=10.0,
        description="0 = only comfort recipes; 10 = always pushing boundaries"
    )
    dining_score:  float = Field(
        default=5.0, ge=0.0, le=10.0,
        description="0 = same restaurant every time; 10 = always discovering new places"
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.IMPORTANT, confidence=0.5)
    )


# ---------------------------------------------------------------------------
# Nutritional awareness
# ---------------------------------------------------------------------------

class NutritionalProfile(BaseModel):
    level: NutritionalAwarenessLevel = Field(default=NutritionalAwarenessLevel.NONE)
    tracked_dimensions: list[str] = Field(
        default_factory=list,
        description=(
            "Which nutritional dimensions the user actively tracks. "
            "E.g. ['calories', 'protein', 'carbs', 'sodium', 'fiber']. "
            "Only meaningful when level >= moderate."
        )
    )
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.CONTEXTUAL, confidence=0.6)
    )


# ---------------------------------------------------------------------------
# Social & behavioral context
# ---------------------------------------------------------------------------

class SocialProfile(BaseModel):
    default_social_context: SocialContext = Field(default=SocialContext.COUPLE)
    meals_out_per_week:     float = Field(default=2.0, ge=0.0)
    home_cooked_per_week:   float = Field(default=4.0, ge=0.0)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.OPTIONAL, confidence=0.5)
    )


# ---------------------------------------------------------------------------
# Preferences and lifestyle
# ---------------------------------------------------------------------------

class LifestyleProfile(BaseModel):
    seasonal_preference_score:   float = Field(
        default=5.0, ge=0.0, le=10.0,
        description="0 = ignores seasons; 10 = always wants seasonal ingredients"
    )
    sustainability_priority_score: float = Field(
        default=5.0, ge=0.0, le=10.0,
        description="0 = doesn't care; 10 = sustainability is a hard criterion"
    )
    special_interests: list[str] = Field(
        default_factory=list,
        description=(
            "Interest tags that drive discovery and content. "
            "E.g. ['wine_pairing', 'fermentation', 'baking', 'bbq', "
            "'meal_prep', 'zero_waste', 'sourdough', 'foraging', 'cocktails']"
        )
    )
    inspiration_style: InspirationStyle = Field(default=InspirationStyle.SHORT_LIST)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.OPTIONAL, confidence=0.5)
    )


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class LocationProfile(BaseModel):
    city:      Optional[str]  = None
    country:   Optional[str]  = None
    radius_km: float          = Field(default=5.0, ge=0.0)
    meta: DimensionMeta = Field(
        default_factory=lambda: DimensionMeta(weight=DimensionWeight.CORE, confidence=0.8)
    )


# ---------------------------------------------------------------------------
# Contradiction / tension tracking
# ---------------------------------------------------------------------------

class ProfileTension(BaseModel):
    """
    A detected contradiction between two profile dimensions.
    Stored non-destructively — neither value is overwritten.
    The tension is surfaced to the user for clarification at an appropriate moment.
    """
    dimension_a: str = Field(..., description="Dotted path to first dimension, e.g. 'dietary.spectrum_label'")
    dimension_b: str = Field(..., description="Dotted path to second dimension, e.g. 'cuisine_affinities.affinities[5]'")
    description: str = Field(..., description="Human-readable explanation of the contradiction")
    severity:    TensionSeverity = Field(default=TensionSeverity.LOW)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    resolved:    bool = Field(default=False)
    resolution_note: Optional[str] = None

    class Config:
        # Example:
        # dimension_a = "dietary.spectrum_label" (value: "vegan")
        # dimension_b = "cuisine_affinities.affinities[?cuisine='Japanese']" (level: love)
        # description = "User identifies as vegan but has 'love' affinity for Japanese cuisine,
        #                which typically includes fish, dashi, and eggs. Possible nuance:
        #                'vegan-leaning' or sub_nuances needed."
        # severity = medium
        pass


# ---------------------------------------------------------------------------
# Root Personal Ontology model
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """
    The complete Personal Ontology for a miam user.
    This is the central semantic object that persists, evolves, and drives
    all retrieval and ranking decisions.
    """
    # Identity
    profile_id:   UUID    = Field(default_factory=uuid4)
    user_id:      UUID    = Field(..., description="Foreign key to auth.users")
    schema_version: str   = Field(default="1.0.0", description="Semver — bump minor on new optional fields, major on breaking changes")
    created_at:   datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Core dimensions
    dietary:          DietaryProfile          = Field(default_factory=DietaryProfile)
    cuisine_affinities: CuisineAffinityProfile = Field(default_factory=CuisineAffinityProfile)
    flavor:           FlavorProfile           = Field(default_factory=FlavorProfile)
    texture:          TextureProfile          = Field(default_factory=TextureProfile)
    cooking:          CookingContext          = Field(default_factory=CookingContext)
    budget:           BudgetProfile           = Field(default_factory=BudgetProfile)
    dining_vibe:      DiningVibeProfile       = Field(default_factory=DiningVibeProfile)
    adventurousness:  AdventurousnessProfile  = Field(default_factory=AdventurousnessProfile)
    nutrition:        NutritionalProfile      = Field(default_factory=NutritionalProfile)
    social:           SocialProfile           = Field(default_factory=SocialProfile)
    lifestyle:        LifestyleProfile        = Field(default_factory=LifestyleProfile)
    location:         LocationProfile         = Field(default_factory=LocationProfile)

    # Tension registry
    tensions: list[ProfileTension] = Field(
        default_factory=list,
        description="Active contradictions detected in this profile. Non-destructive."
    )

    # Human-readable summary
    profile_summary_text: Optional[str] = Field(
        default=None,
        description=(
            "2–4 sentence natural-language summary of this user's food identity. "
            "Shown on the profile page and used as context prefix in LLM calls. "
            "Regenerated by Agent C after significant updates."
        )
    )

    # Onboarding state
    onboarding_complete: bool = Field(default=False)
    onboarding_version:  str  = Field(default="1.0.0")

    @model_validator(mode="after")
    def detect_tensions(self) -> "UserProfile":
        """
        Passive tension detection on construction/update.
        Does not raise — only registers tensions in self.tensions.
        """
        new_tensions: list[ProfileTension] = []

        # Rule 1: vegan hard stop + cuisine affinity that implies animal products
        animal_product_cuisines = {
            "Japanese", "Korean", "Thai", "Vietnamese", "French",
            "Spanish", "Italian", "Greek", "Turkish", "Peruvian"
        }
        dietary_label = (self.dietary.spectrum_label or "").lower()
        hard_stop_labels = {r.label.lower() for r in self.dietary.hard_stops}

        is_strict_vegan = "vegan" in dietary_label and "flexitarian" not in dietary_label
        has_meat_stop   = any(l in hard_stop_labels for l in ("meat", "fish", "seafood", "eggs", "dairy"))

        if is_strict_vegan or has_meat_stop:
            for aff in self.cuisine_affinities.affinities:
                if aff.level in (PreferenceLevel.LOVE, PreferenceLevel.LIKE):
                    if aff.cuisine in animal_product_cuisines:
                        new_tensions.append(ProfileTension(
                            dimension_a="dietary.spectrum_label",
                            dimension_b=f"cuisine_affinities.affinities[cuisine='{aff.cuisine}']",
                            description=(
                                f"Profile indicates strict dietary restriction "
                                f"('{self.dietary.spectrum_label}') but has "
                                f"'{aff.level}' affinity for {aff.cuisine} cuisine, "
                                f"which typically includes restricted ingredients. "
                                f"Consider adding sub_nuances or adjusting the label."
                            ),
                            severity=TensionSeverity.MEDIUM
                        ))

        # Rule 2: spicy score very low + any cuisine affinity for high-spice cuisines flagged as love
        high_spice_cuisines = {"Thai", "Sichuan", "Korean", "Indian", "Ethiopian", "Mexican"}
        if self.flavor.spicy is not None and self.flavor.spicy <= 2.0:
            for aff in self.cuisine_affinities.affinities:
                if aff.level == PreferenceLevel.LOVE and aff.cuisine in high_spice_cuisines:
                    new_tensions.append(ProfileTension(
                        dimension_a="flavor.spicy",
                        dimension_b=f"cuisine_affinities.affinities[cuisine='{aff.cuisine}']",
                        description=(
                            f"Spicy preference is very low ({self.flavor.spicy}/10) "
                            f"but '{aff.cuisine}' is marked as 'love'. "
                            f"Suggest adding sub_nuance 'prefer mild versions'."
                        ),
                        severity=TensionSeverity.LOW
                    ))

        # Rule 3: budget low + sustainability very high (organic/sustainable food costs more)
        if (self.budget.out_per_meal_eur is not None
                and self.budget.out_per_meal_eur < 15.0
                and self.lifestyle.sustainability_priority_score >= 8.0):
            new_tensions.append(ProfileTension(
                dimension_a="budget.out_per_meal_eur",
                dimension_b="lifestyle.sustainability_priority_score",
                description=(
                    "High sustainability priority (≥8/10) combined with a low "
                    "dining budget (<€15/meal) may produce very few results. "
                    "Consider relaxing one constraint."
                ),
                severity=TensionSeverity.LOW
            ))

        # Merge: keep existing resolved tensions, append new unresolved ones
        existing_unresolved = [t for t in self.tensions if not t.resolved]
        existing_resolved   = [t for t in self.tensions if t.resolved]

        # Deduplicate by (dimension_a, dimension_b) pair
        existing_keys = {(t.dimension_a, t.dimension_b) for t in existing_unresolved}
        for t in new_tensions:
            if (t.dimension_a, t.dimension_b) not in existing_keys:
                existing_unresolved.append(t)

        self.tensions = existing_resolved + existing_unresolved
        return self

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat(), UUID: str}
