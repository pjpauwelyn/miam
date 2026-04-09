from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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
    kcal: int
    protein_g: float
    fat_g: float
    saturated_fat_g: float
    carbs_g: float
    fiber_g: float
    sugar_g: float
    salt_g: float


class RecipeDocument(BaseModel):
    """
    Canonical recipe document stored in the miam database and indexed for RAG retrieval.
    Schema is a strict superset of RecipeNLG fields, extended with miam-specific fields.
    """
    id: UUID = Field(default_factory=uuid4)

    # Identity & classification
    title: str = Field(..., description="Title in original language")
    title_en: str = Field(..., description="English title (always populated)")
    cuisine_tags: list[str] = Field(default_factory=list)
    region_tag: Optional[str] = Field(
        default=None,
        description="E.g. 'Provence', 'Noord-Brabant', 'Veneto'"
    )
    description: str = Field(
        ...,
        description="100-200 words, written for European audience"
    )

    # Recipe content
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    steps: list[RecipeStep] = Field(default_factory=list)

    # Timing & difficulty
    time_prep_min: int = Field(..., ge=0)
    time_cook_min: int = Field(..., ge=0)
    time_total_min: int = Field(
        ..., ge=0,
        description="Computed: prep + cook"
    )
    serves: int = Field(..., ge=1)
    difficulty: int = Field(
        ..., ge=1, le=5,
        description="1=beginner, 5=professional"
    )

    # Semantic tags
    flavor_tags: list[str] = Field(
        default_factory=list,
        description="E.g. ['umami', 'acidic', 'sweet', 'bitter', 'spicy', 'herbaceous', 'smoky', 'rich', 'light']"
    )
    texture_tags: list[str] = Field(
        default_factory=list,
        description="E.g. ['creamy', 'crispy', 'tender', 'crunchy', 'silky', 'chunky']"
    )
    dietary_tags: list[str] = Field(
        default_factory=list,
        description="Human-readable array for display and fuzzy matching"
    )

    # Dietary flags (structured booleans for precise programmatic filtering)
    dietary_flags: DietaryFlags = Field(default_factory=DietaryFlags)

    # Nutrition
    nutrition_per_serving: Optional[NutritionPerServing] = None

    # Context tags
    season_tags: list[str] = Field(
        default_factory=list,
        description="spring | summer | autumn | winter | year-round"
    )
    occasion_tags: list[str] = Field(
        default_factory=list,
        description="E.g. 'weeknight', 'dinner-party', 'date-night', 'christmas', 'easter', 'bbq', 'picnic', 'comfort-food', 'meal-prep'"
    )
    course_tags: list[str] = Field(
        default_factory=list,
        description="starter | main | side | dessert | snack | breakfast | soup | salad"
    )

    # Media & metadata
    image_placeholder: Optional[str] = Field(
        default=None,
        description="Descriptive alt-text for AI image generation prompt"
    )
    source_type: str = Field(
        default="ai-generated",
        description="ai-generated | adapted-from-classic | regional-traditional"
    )
    wine_pairing_notes: Optional[str] = None
    tips: list[str] = Field(default_factory=list)

    # RAG embedding
    embedding_text: str = Field(
        ...,
        description=(
            "Pre-computed concatenation of title_en + description + ingredient names "
            "+ flavor_tags + texture_tags + dietary_tags + occasion_tags"
        )
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    data_quality_score: float = Field(
        default=0.95, ge=0.0, le=1.0,
        description="0.95 for standard records; lower for edge cases"
    )
