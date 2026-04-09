"""
TheMealDBAdapter — Tier 0 only.

Converts TheMealDB flat strIngredient1..20 format to RecipeDocument.
Used in Phase 0 for schema reference only — not a production data source.

TheMealDB has ~300 recipes using flat strIngredient1..20 + strMeasure1..20
fields with no structured amounts, no EU measurements, and no nutritional data.
"""
from __future__ import annotations

from uuid import uuid4
from datetime import datetime

from .base import BaseAdapter

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from models.recipe import (
    RecipeDocument,
    RecipeIngredient,
    RecipeStep,
    DietaryFlags,
    NutritionPerServing,
)


class TheMealDBAdapter(BaseAdapter):
    """Convert TheMealDB flat strIngredient1..20 format to RecipeDocument.
    Used in Phase 0 for schema reference only — not a production data source."""

    def adapt(self, raw: dict) -> RecipeDocument:
        """Map strIngredient1..20 + strMeasure1..20 -> ingredients[]"""
        # Extract ingredients from flat fields
        ingredients = []
        for i in range(1, 21):
            name = (raw.get(f"strIngredient{i}") or "").strip()
            measure = (raw.get(f"strMeasure{i}") or "").strip()
            if not name:
                continue

            # Parse measure into amount and unit (best-effort)
            amount, unit = self._parse_measure(measure)
            ingredients.append(
                RecipeIngredient(
                    name=name,
                    amount=amount,
                    unit=unit,
                    notes=measure if measure else None,
                    is_optional=False,
                    substitutions=[],
                )
            )

        # Extract steps from instructions
        instructions = raw.get("strInstructions", "")
        steps = []
        for i, line in enumerate(instructions.split("\r\n"), 1):
            line = line.strip()
            if line:
                steps.append(
                    RecipeStep(
                        step_number=i,
                        instruction=line,
                        duration_min=None,
                        technique_tags=[],
                    )
                )

        # If no steps parsed from newlines, treat as a single step
        if not steps and instructions.strip():
            steps = [
                RecipeStep(
                    step_number=1,
                    instruction=instructions.strip(),
                    duration_min=None,
                    technique_tags=[],
                )
            ]

        title = raw.get("strMeal", "Unknown Recipe")
        cuisine = raw.get("strArea", "Unknown")
        category = raw.get("strCategory", "")

        # Build embedding text
        ingredient_names = " ".join(i.name for i in ingredients)
        embedding_text = f"{title} {cuisine} {category} {ingredient_names}"

        return RecipeDocument(
            id=str(uuid4()),
            title=title,
            title_en=title,
            cuisine_tags=[cuisine] if cuisine else [],
            region_tag=None,
            description=f"A {cuisine} {category.lower()} dish.",
            ingredients=ingredients,
            steps=steps,
            time_prep_min=15,  # TheMealDB has no time data — use defaults
            time_cook_min=30,
            time_total_min=45,
            serves=4,
            difficulty=2,
            flavor_tags=[],
            texture_tags=[],
            dietary_tags=[category.lower()] if category else [],
            dietary_flags=DietaryFlags(),  # Defaults; TheMealDB has no dietary info
            nutrition_per_serving=NutritionPerServing(
                kcal=0, protein_g=0, fat_g=0, saturated_fat_g=0,
                carbs_g=0, fiber_g=0, sugar_g=0, salt_g=0,
            ),
            season_tags=["year-round"],
            occasion_tags=[],
            course_tags=[category.lower()] if category else [],
            image_placeholder=raw.get("strMealThumb", ""),
            source_type="themealdb",
            wine_pairing_notes=None,
            tips=[],
            embedding_text=embedding_text,
            created_at=datetime.utcnow().isoformat(),
            data_quality_score=0.3,  # Low score — TheMealDB data is sparse
        )

    @staticmethod
    def _parse_measure(measure: str) -> tuple[float, str]:
        """Best-effort parse of TheMealDB measure strings like '1 cup', '200g'."""
        if not measure:
            return 1.0, "piece"

        measure = measure.strip().lower()

        # Try to extract a number
        import re
        match = re.match(r"([\d./]+)\s*(.*)", measure)
        if match:
            num_str = match.group(1)
            unit_str = match.group(2).strip() or "piece"
            try:
                if "/" in num_str:
                    parts = num_str.split("/")
                    amount = float(parts[0]) / float(parts[1])
                else:
                    amount = float(num_str)
            except (ValueError, ZeroDivisionError):
                amount = 1.0
            return amount, unit_str

        return 1.0, measure or "piece"
