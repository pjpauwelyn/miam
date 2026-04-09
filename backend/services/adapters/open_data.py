"""
OpenDataAdapter — converts enriched RecipeNLG records to canonical RecipeDocument.

Phase 1.1 adapter: takes the output of the enrichment pipeline
(recipenlg_enriched_2000.jsonl) and produces full RecipeDocument instances
ready for Supabase ingestion.

Uses:
- LLM-generated enrichment for description, tags, timing
- CIQUAL-based nutrition lookup
- Rule-based dietary flag inference
- EU/British English normalisation via SynonymResolver
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from .base import BaseAdapter
from models.recipe import (
    RecipeDocument,
    RecipeIngredient,
    RecipeStep,
    DietaryFlags,
    NutritionPerServing,
)
from services.synonym_resolver import normalize_ingredient
from services.embeddings import build_recipe_embedding_text


def _ensure_list(value, default: list | None = None) -> list:
    """Coerce a value to a list. Handles bare strings from LLM output."""
    if value is None:
        return default if default is not None else []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        # Split comma-separated strings, or wrap single values
        if "," in value:
            return [v.strip() for v in value.split(",") if v.strip()]
        return [value.strip()] if value.strip() else (default if default is not None else [])
    return default if default is not None else []


# Controlled cuisine vocabulary — normalise LLM outputs to these
VALID_CUISINES = {
    "italian", "french", "spanish", "greek", "moroccan",
    "lebanese", "turkish", "indian", "chinese", "japanese",
    "korean", "thai", "vietnamese", "mexican", "peruvian",
    "american", "british", "german", "dutch", "scandinavian",
    "middle eastern", "african", "caribbean", "fusion", "other",
}

# Map non-standard LLM cuisine outputs to controlled vocabulary
CUISINE_NORMALISATION = {
    "swedish": "Scandinavian", "norwegian": "Scandinavian",
    "danish": "Scandinavian", "finnish": "Scandinavian",
    "mediterranean": "Fusion", "cajun": "American",
    "cuban": "Caribbean", "creole": "American",
    "irish": "British", "scottish": "British", "welsh": "British",
    "austrian": "German", "swiss": "German",
    "hungarian": "Fusion", "polish": "Fusion",
    "serbian": "Fusion", "croatian": "Fusion",
    "malaysian": "Fusion", "indonesian": "Fusion",
    "pakistani": "Indian", "sri lankan": "Indian",
    "ethiopian": "African", "nigerian": "African",
    "south african": "African", "west african": "African",
}


class OpenDataAdapter(BaseAdapter):
    """
    Convert an enriched RecipeNLG record to a canonical RecipeDocument.

    Expected input: dict from recipenlg_enriched_2000.jsonl with keys:
    - title, ingredients, directions, NER, link, source
    - _enrichment: {description, difficulty, cuisine, flavor_tags, texture_tags,
                    season_tags, occasion_tags, course_tags, time_prep_min,
                    time_cook_min, serves}
    - _nutrition: {kcal, protein_g, fat_g, saturated_fat_g, carbs_g,
                   fiber_g, sugar_g, salt_g} or None
    - _dietary_flags: {is_vegan, is_vegetarian, ...}
    - _dietary_tags: [...]
    """

    def adapt(self, raw: dict) -> RecipeDocument:
        """Convert enriched RecipeNLG record to RecipeDocument."""
        enrichment = raw.get("_enrichment", {})
        title = raw.get("title", "Untitled Recipe")

        # Build ingredients from NER + ingredient text
        ingredients = self._build_ingredients(raw)

        # Build steps
        steps = self._build_steps(raw)

        # Normalise cuisine
        cuisine = self._normalise_cuisine(enrichment.get("cuisine", "Other"))
        cuisine_tags = [cuisine]

        # Dietary flags
        flags_dict = raw.get("_dietary_flags", {})
        dietary_flags = DietaryFlags(
            is_vegan=flags_dict.get("is_vegan", False),
            is_vegetarian=flags_dict.get("is_vegetarian", False),
            is_pescatarian_ok=flags_dict.get("is_pescatarian_ok", False),
            is_dairy_free=flags_dict.get("is_dairy_free", False),
            is_gluten_free=flags_dict.get("is_gluten_free", False),
            is_nut_free=flags_dict.get("is_nut_free", False),
            is_halal_ok=flags_dict.get("is_halal_ok", False),
            contains_pork=flags_dict.get("contains_pork", False),
            contains_shellfish=flags_dict.get("contains_shellfish", False),
            contains_alcohol=flags_dict.get("contains_alcohol", False),
            vegan_if_substituted=flags_dict.get("vegan_if_substituted", False),
            gluten_free_if_substituted=flags_dict.get("gluten_free_if_substituted", False),
        )

        # Nutrition
        nutr_dict = raw.get("_nutrition")
        nutrition = None
        if nutr_dict:
            nutrition = NutritionPerServing(
                kcal=max(1, int(nutr_dict.get("kcal", 0))),
                protein_g=round(float(nutr_dict.get("protein_g", 0)), 1),
                fat_g=round(float(nutr_dict.get("fat_g", 0)), 1),
                saturated_fat_g=round(float(nutr_dict.get("saturated_fat_g", 0)), 1),
                carbs_g=round(float(nutr_dict.get("carbs_g", 0)), 1),
                fiber_g=round(float(nutr_dict.get("fiber_g", 0)), 1),
                sugar_g=round(float(nutr_dict.get("sugar_g", 0)), 1),
                salt_g=round(float(nutr_dict.get("salt_g", 0)), 2),
            )

        # Timing
        time_prep = int(enrichment.get("time_prep_min", 15))
        time_cook = int(enrichment.get("time_cook_min", 30))
        time_total = time_prep + time_cook

        # Description
        description = enrichment.get("description", f"A recipe for {title}.")
        if len(description) < 30:
            description = f"A delicious recipe for {title}. {description}"

        # Tags — coerce bare strings from LLM to lists
        flavor_tags = _ensure_list(enrichment.get("flavor_tags"), [])
        texture_tags = _ensure_list(enrichment.get("texture_tags"), [])
        season_tags = _ensure_list(enrichment.get("season_tags"), ["year-round"])
        occasion_tags = _ensure_list(enrichment.get("occasion_tags"), ["weeknight"])
        course_tags = _ensure_list(enrichment.get("course_tags"), ["main"])
        dietary_tags = _ensure_list(raw.get("_dietary_tags"), [])

        # Data quality score
        quality_score = self._compute_quality_score(
            description, ingredients, steps, flavor_tags, texture_tags,
            nutrition, cuisine, time_prep, time_cook
        )

        # Build embedding text
        recipe_dict = {
            "title_en": title,
            "description": description,
            "ingredients": [{"name": i.name} for i in ingredients],
            "flavor_tags": flavor_tags,
            "texture_tags": texture_tags,
            "dietary_tags": dietary_tags,
            "occasion_tags": occasion_tags,
            "season_tags": season_tags,
            "cuisine_tags": cuisine_tags,
        }
        embedding_text = build_recipe_embedding_text(recipe_dict)

        return RecipeDocument(
            id=str(uuid4()),
            title=title,
            title_en=title,
            cuisine_tags=cuisine_tags,
            region_tag=None,
            description=description,
            ingredients=ingredients,
            steps=steps,
            time_prep_min=time_prep,
            time_cook_min=time_cook,
            time_total_min=time_total,
            serves=max(1, int(enrichment.get("serves", 4))),
            difficulty=max(1, min(5, int(enrichment.get("difficulty", 2)))),
            flavor_tags=flavor_tags,
            texture_tags=texture_tags,
            dietary_tags=dietary_tags,
            dietary_flags=dietary_flags,
            nutrition_per_serving=nutrition,
            season_tags=season_tags,
            occasion_tags=occasion_tags,
            course_tags=course_tags,
            image_placeholder=f"A beautifully plated {title.lower()}, shot from above on a rustic wooden table.",
            source_type="recipenlg_enriched",
            wine_pairing_notes=None,
            tips=[],
            embedding_text=embedding_text,
            created_at=datetime.utcnow().isoformat(),
            data_quality_score=quality_score,
        )

    def _build_ingredients(self, raw: dict) -> list[RecipeIngredient]:
        """Build RecipeIngredient list from NER + ingredient texts."""
        ner_items = raw.get("NER", [])
        ingredient_texts = raw.get("ingredients", [])
        ingredients = []

        for i, name in enumerate(ner_items):
            full_text = ingredient_texts[i] if i < len(ingredient_texts) else None
            normalised_name = normalize_ingredient(name.strip())
            amount, unit = self._parse_ingredient_text(full_text) if full_text else (1.0, "piece")

            ingredients.append(RecipeIngredient(
                name=normalised_name,
                amount=amount,
                unit=unit,
                notes=full_text,
                is_optional=False,
                substitutions=[],
            ))

        return ingredients

    def _build_steps(self, raw: dict) -> list[RecipeStep]:
        """Build RecipeStep list from directions."""
        directions = raw.get("directions", [])
        steps = []
        for i, instruction in enumerate(directions, 1):
            if instruction.strip():
                steps.append(RecipeStep(
                    step_number=i,
                    instruction=instruction.strip(),
                    duration_min=None,
                    technique_tags=[],
                ))
        return steps

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

    def _normalise_cuisine(self, cuisine: str) -> str:
        """Normalise cuisine tag to controlled vocabulary."""
        if not cuisine:
            return "Other"
        lower = cuisine.lower().strip()
        # Check if already valid
        if lower in VALID_CUISINES:
            return cuisine.title() if lower != "middle eastern" else "Middle Eastern"
        # Check normalisation map
        if lower in CUISINE_NORMALISATION:
            return CUISINE_NORMALISATION[lower]
        return "Other"

    @staticmethod
    def _compute_quality_score(
        description: str,
        ingredients: list,
        steps: list,
        flavor_tags: list,
        texture_tags: list,
        nutrition: Optional[NutritionPerServing],
        cuisine: str,
        time_prep: int,
        time_cook: int,
    ) -> float:
        """Compute data quality score from field completeness (0.0–1.0)."""
        score = 1.0

        # Deductions for missing/weak fields
        if not description or len(description) < 30:
            score -= 0.1
        if len(ingredients) < 3:
            score -= 0.15
        if len(steps) < 2:
            score -= 0.1
        if not flavor_tags:
            score -= 0.05
        if not texture_tags:
            score -= 0.05
        if nutrition is None:
            score -= 0.1
        if cuisine == "Other":
            score -= 0.05
        if time_prep == 0 and time_cook == 0:
            score -= 0.1

        return max(0.0, min(1.0, round(score, 2)))
