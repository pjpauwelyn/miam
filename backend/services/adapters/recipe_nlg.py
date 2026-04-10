"""
RecipeNLGAdapter — Tier 1 adapter for the RecipeNLG dataset (220k+ recipes).

Converts RecipeNLG records (NER[] + directions[]) to canonical RecipeDocument.
Activated in Phase 3 when the real RecipeNLG dataset replaces Tier 0 mock data.
"""
from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone

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


class RecipeNLGAdapter(BaseAdapter):
    """
    Convert RecipeNLG records to canonical RecipeDocument.

    RecipeNLG schema:
    {
        "title": "...",
        "ingredients": ["1 cup flour", "2 eggs"],
        "directions": ["Mix flour...", "Add eggs..."],
        "NER": ["flour", "eggs"],
        "link": "...",
        "source": "..."
    }
    """

    def adapt(self, raw: dict) -> RecipeDocument:
        """Map RecipeNLG NER[] + directions[] to RecipeDocument."""
        title = raw.get("title", "Untitled Recipe")

        # Build ingredients from NER (ingredient names) and ingredients (full text)
        ner_items = raw.get("NER", [])
        ingredient_texts = raw.get("ingredients", [])
        ingredients = []

        for i, name in enumerate(ner_items):
            # Try to get the full ingredient text for notes
            full_text = ingredient_texts[i] if i < len(ingredient_texts) else None
            amount, unit = self._parse_ingredient_text(full_text) if full_text else (1.0, "piece")

            ingredients.append(
                RecipeIngredient(
                    name=name.strip(),
                    amount=amount,
                    unit=unit,
                    notes=full_text,
                    is_optional=False,
                    substitutions=[],
                )
            )

        # Build steps from directions
        directions = raw.get("directions", [])
        steps = []
        for i, instruction in enumerate(directions, 1):
            if instruction.strip():
                steps.append(
                    RecipeStep(
                        step_number=i,
                        instruction=instruction.strip(),
                        duration_min=None,
                        technique_tags=[],
                    )
                )

        # Build embedding text
        ingredient_names = " ".join(i.name for i in ingredients)
        embedding_text = f"{title} {ingredient_names}"

        return RecipeDocument(
            id=str(uuid4()),
            title=title,
            title_en=title,
            cuisine_tags=[],  # RecipeNLG doesn't have cuisine tags — assigned by NLP
            description=f"Recipe: {title}",
            ingredients=ingredients,
            steps=steps,
            time_prep_min=15,  # RecipeNLG doesn't have time data
            time_cook_min=30,
            time_total_min=45,
            serves=4,
            difficulty=2,
            flavor_tags=[],
            texture_tags=[],
            dietary_tags=[],  # Derived from NER analysis
            dietary_flags=DietaryFlags(),
            nutrition_per_serving=NutritionPerServing(
                kcal=None, protein_g=None, fat_g=None, saturated_fat_g=None,
                carbs_g=None, fiber_g=None, sugar_g=None, salt_g=None,
            ),
            season_tags=["year-round"],
            occasion_tags=[],
            course_tags=[],
            source_type="recipenlg",
            embedding_text=embedding_text,
            created_at=datetime.now(timezone.utc).isoformat(),
            data_quality_score=0.5,  # RecipeNLG records are often incomplete
        )

    @staticmethod
    def _parse_ingredient_text(text: str) -> tuple[float, str]:
        """Best-effort parse of ingredient text like '1 cup flour'."""
        import re
        match = re.match(r"([\d./ ]+)\s+([\w]+)\s+", text.strip())
        if match:
            try:
                num_str = match.group(1).strip()
                if "/" in num_str:
                    parts = num_str.split("/")
                    amount = float(parts[0]) / float(parts[1])
                else:
                    amount = float(num_str)
                return amount, match.group(2)
            except (ValueError, ZeroDivisionError):
                pass
        return 1.0, "piece"
