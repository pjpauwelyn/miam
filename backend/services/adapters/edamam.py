"""
EdamamAdapter — Tier 2 paid API adapter (DORMANT).

Normalises Edamam recipe API responses to the canonical RecipeDocument schema.
LOCKED until TIER2_APPROVED=true is set by stakeholder.

Edamam pricing: ~$99/month. No API key may be configured without
written stakeholder sign-off.
"""
from __future__ import annotations

import os

from .base import BaseAdapter, TierNotApprovedError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.recipe import (
    RecipeDocument,
    RecipeIngredient,
    RecipeStep,
    DietaryFlags,
    NutritionPerServing,
)
from uuid import uuid4
from datetime import datetime


class EdamamAdapter(BaseAdapter):
    """
    Converts Edamam recipe API responses to RecipeDocument.
    Tier 2 — dormant until TIER2_APPROVED=true.

    Edamam response structure:
    {
        "recipe": {
            "label": "...",
            "ingredients": [{"food": "...", "quantity": 1.0, "measure": "cup"}],
            "instructionLines": ["..."],
            "totalNutrients": {"ENERC_KCAL": {"quantity": 450}},
            "cuisineType": ["asian"],
            "healthLabels": ["Vegan", "Gluten-Free"]
        }
    }
    """

    def _check_tier_approval(self) -> None:
        """Check that Tier 2 is approved before any operation."""
        if os.getenv("TIER2_APPROVED", "").lower() != "true":
            raise TierNotApprovedError(
                "Edamam is a Tier 2 paid API ($99/month). "
                "Set TIER2_APPROVED=true in .env after stakeholder approval. "
                "Do not configure without written sign-off."
            )

    def adapt(self, raw: dict) -> RecipeDocument:
        """
        Normalise an Edamam recipe response to canonical RecipeDocument.
        Implementation ready — activates only when TIER2_APPROVED=true.
        """
        self._check_tier_approval()

        recipe = raw.get("recipe", raw)

        # Extract ingredients
        ingredients = []
        for ing in recipe.get("ingredients", []):
            ingredients.append(
                RecipeIngredient(
                    name=ing.get("food", "unknown"),
                    amount=ing.get("quantity", 1.0),
                    unit=ing.get("measure", "piece"),
                    notes=ing.get("text"),
                    is_optional=False,
                    substitutions=[],
                )
            )

        # Extract steps
        steps = []
        for i, line in enumerate(recipe.get("instructionLines", []), 1):
            steps.append(
                RecipeStep(
                    step_number=i,
                    instruction=line,
                    duration_min=None,
                    technique_tags=[],
                )
            )

        # Map health labels to dietary flags
        health_labels = set(l.lower() for l in recipe.get("healthLabels", []))
        dietary_flags = DietaryFlags(
            is_vegan="vegan" in health_labels,
            is_vegetarian="vegetarian" in health_labels,
            is_pescatarian_ok="pescatarian" in health_labels,
            is_dairy_free="dairy-free" in health_labels,
            is_gluten_free="gluten-free" in health_labels,
            is_nut_free="tree-nut-free" in health_labels and "peanut-free" in health_labels,
            is_halal_ok=False,  # Edamam doesn't reliably provide halal info
            contains_pork="pork-free" not in health_labels,
            contains_shellfish="crustacean-free" not in health_labels,
            contains_alcohol="alcohol-free" not in health_labels,
        )

        # Extract nutrition
        nutrients = recipe.get("totalNutrients", {})
        servings = recipe.get("yield", 4) or 4
        nutrition = NutritionPerServing(
            kcal=int(nutrients.get("ENERC_KCAL", {}).get("quantity", 0) / servings),
            protein_g=round(nutrients.get("PROCNT", {}).get("quantity", 0) / servings, 1),
            fat_g=round(nutrients.get("FAT", {}).get("quantity", 0) / servings, 1),
            saturated_fat_g=round(nutrients.get("FASAT", {}).get("quantity", 0) / servings, 1),
            carbs_g=round(nutrients.get("CHOCDF", {}).get("quantity", 0) / servings, 1),
            fiber_g=round(nutrients.get("FIBTG", {}).get("quantity", 0) / servings, 1),
            sugar_g=round(nutrients.get("SUGAR", {}).get("quantity", 0) / servings, 1),
            salt_g=round(nutrients.get("NA", {}).get("quantity", 0) / servings / 400, 2),
        )

        title = recipe.get("label", "Unknown")
        ingredient_names = " ".join(i.name for i in ingredients)
        cuisine_types = recipe.get("cuisineType", [])

        return RecipeDocument(
            id=str(uuid4()),
            title=title,
            title_en=title,
            cuisine_tags=cuisine_types,
            description=f"Recipe from Edamam: {title}",
            ingredients=ingredients,
            steps=steps,
            time_prep_min=recipe.get("totalTime", 30) // 3,
            time_cook_min=recipe.get("totalTime", 30) * 2 // 3,
            time_total_min=recipe.get("totalTime", 30),
            serves=int(servings),
            difficulty=2,
            flavor_tags=[],
            texture_tags=[],
            dietary_tags=list(health_labels)[:5],
            dietary_flags=dietary_flags,
            nutrition_per_serving=nutrition,
            season_tags=["year-round"],
            occasion_tags=[],
            course_tags=[],
            source_type="edamam",
            embedding_text=f"{title} {ingredient_names} {' '.join(cuisine_types)}",
            created_at=datetime.utcnow().isoformat(),
            data_quality_score=1.0,  # Edamam records are complete
        )
