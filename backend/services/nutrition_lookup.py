"""
NutritionLookup — unified nutrition lookup service for the miam enrichment pipeline.

Priority chain: CIQUAL (EU, France) → Open Food Facts (EU) → USDA FDC (US, fallback).

For Phase 1.1, only CIQUAL is loaded from the pre-parsed JSON lookup.
OFF and USDA lookups are stubbed — they require downloading large datasets
that are not yet available. The architecture supports adding them later.

Uses rapidfuzz for fuzzy string matching against food names.
Normalises ingredient names via synonym_resolver before lookup.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

# Paths to pre-parsed lookup files (relative to project data dir)
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "open")
_CIQUAL_PATH = os.path.join(_DATA_DIR, "ciqual_lookup.json")
_OFF_PATH = os.path.join(_DATA_DIR, "off_eu_lookup.json")
_USDA_PATH = os.path.join(_DATA_DIR, "usda_lookup.json")

# Fuzzy match threshold (0-100). 70 gives good recall without too many false positives.
_FUZZY_THRESHOLD = 70


@dataclass
class NutritionPer100g:
    """Nutrition values per 100g of food."""
    kcal: float
    protein_g: float
    fat_g: float
    saturated_fat_g: float
    carbs_g: float
    fiber_g: float
    sugar_g: float
    salt_g: float
    source: str  # "ciqual", "off", or "usda"


class NutritionLookup:
    """
    Unified nutrition lookup across CIQUAL → OFF → USDA.

    Lazily loads lookup dicts on first call. Thread-safe via module-level
    singleton pattern (Python GIL).
    """

    def __init__(self) -> None:
        self._ciqual: dict[str, dict] | None = None
        self._off: dict[str, dict] | None = None
        self._usda: dict[str, dict] | None = None
        self._ciqual_names: list[str] | None = None
        self._off_names: list[str] | None = None
        self._usda_names: list[str] | None = None
        # Stats tracking
        self.stats = {"total": 0, "ciqual_hit": 0, "off_hit": 0, "usda_hit": 0, "miss": 0}

    def _load_ciqual(self) -> None:
        """Load CIQUAL lookup from pre-parsed JSON."""
        if self._ciqual is not None:
            return
        if not os.path.exists(_CIQUAL_PATH):
            logger.warning("CIQUAL lookup not found at %s — nutrition lookup degraded", _CIQUAL_PATH)
            self._ciqual = {}
            self._ciqual_names = []
            return
        with open(_CIQUAL_PATH, "r", encoding="utf-8") as f:
            self._ciqual = json.load(f)
        self._ciqual_names = list(self._ciqual.keys())
        logger.info("Loaded CIQUAL lookup: %d foods", len(self._ciqual))

    def _load_off(self) -> None:
        """Load Open Food Facts EU lookup from pre-parsed JSON."""
        if self._off is not None:
            return
        if not os.path.exists(_OFF_PATH):
            logger.debug("OFF EU lookup not found at %s — skipping OFF tier", _OFF_PATH)
            self._off = {}
            self._off_names = []
            return
        with open(_OFF_PATH, "r", encoding="utf-8") as f:
            self._off = json.load(f)
        self._off_names = list(self._off.keys())
        logger.info("Loaded OFF EU lookup: %d products", len(self._off))

    def _load_usda(self) -> None:
        """Load USDA FDC lookup from pre-parsed JSON."""
        if self._usda is not None:
            return
        if not os.path.exists(_USDA_PATH):
            logger.debug("USDA lookup not found at %s — skipping USDA tier", _USDA_PATH)
            self._usda = {}
            self._usda_names = []
            return
        with open(_USDA_PATH, "r", encoding="utf-8") as f:
            self._usda = json.load(f)
        self._usda_names = list(self._usda.keys())
        logger.info("Loaded USDA lookup: %d foods", len(self._usda))

    def _ensure_loaded(self) -> None:
        """Lazy-load all lookup dicts."""
        self._load_ciqual()
        self._load_off()
        self._load_usda()

    def _fuzzy_search(
        self,
        query: str,
        choices: list[str],
        data: dict[str, dict],
        source_label: str,
    ) -> Optional[NutritionPer100g]:
        """
        Fuzzy-match query against a list of food names.
        Returns NutritionPer100g if a match above threshold is found.

        Strategy:
        1. Exact match (case-insensitive)
        2. Check common ingredient patterns ("X, raw", "X, cooked", etc.)
        3. Fuzzy match with token_sort_ratio, preferring shorter (simpler) entries
           to avoid matching "chicken" to "caesar salad with chicken"
        """
        if not choices:
            return None

        query_lower = query.lower().strip()

        # 1. Exact match
        if query_lower in data:
            return self._entry_to_nutrition(data[query_lower], source_label)

        # 2. Try common CIQUAL naming patterns for raw ingredients
        pattern_variants = [
            f"{query_lower}, raw",
            f"{query_lower}, raw (average)",
            f"{query_lower}, all types, raw",
            f"{query_lower}, flesh and skin, raw",
            f"{query_lower}, flesh without skin, raw",
            f"{query_lower}, flesh without skin, without seeds, raw",
            f"{query_lower} (average)",
            f"{query_lower}, cooked (average)",
            f"{query_lower}, cooked",
            f"{query_lower}, white, cooked, no added salt",
            f"{query_lower}, white",
            f"{query_lower}, extra virgin",
            f"{query_lower}, whole (average)",
            f"{query_lower}, whole, raw",
            f"{query_lower}, breast, raw",
            f"{query_lower}, breast, cooked",
            f"{query_lower}, leg, roasted/baked",
            f"{query_lower}, shoulder, cooked",
            f"{query_lower}, chop, grilled/pan-fried",
            f"{query_lower}, steamed",
            f"{query_lower}, boiled/cooked in water",
            f"{query_lower}, peeled, raw",
            f"{query_lower}, peeled, boiled/cooked in water",
        ]
        for variant in pattern_variants:
            if variant in data:
                logger.debug(
                    "Pattern match: '%s' → '%s' (source=%s)",
                    query, variant, source_label,
                )
                return self._entry_to_nutrition(data[variant], source_label)

        # 3. Starts-with match — find entries that begin with the query term
        #    followed by a comma. Prefer shorter names (raw ingredients).
        starts_with = [
            name for name in choices
            if name.startswith(query_lower + ",") or name.startswith(query_lower + " ")
        ]
        if starts_with:
            # Prefer entries containing "raw" or short entries
            raw_entries = [n for n in starts_with if "raw" in n]
            cooked_entries = [n for n in starts_with if "cooked" in n or "steamed" in n]
            # Priority: raw > cooked > shortest
            candidates = raw_entries or cooked_entries or starts_with
            candidates.sort(key=len)
            matched_name = candidates[0]
            logger.debug(
                "Starts-with match: '%s' → '%s' (source=%s)",
                query, matched_name, source_label,
            )
            return self._entry_to_nutrition(data[matched_name], source_label)

        # 4. Fuzzy match — get top 5 candidates and prefer shorter names
        #    (shorter names = simpler/raw ingredients, not composite dishes)
        results = process.extract(
            query_lower,
            choices,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=_FUZZY_THRESHOLD,
            limit=10,
        )
        if results:
            # Filter out composite dishes (long names with many commas)
            # and names where the query is just a minor component
            filtered = []
            for name, score, idx in results:
                # Skip if name has more than 4 comma-separated parts (likely a dish)
                parts = name.split(",")
                if len(parts) > 4:
                    continue
                # Skip if the query only appears as a modifier (e.g. "chicken fat" for "chicken")
                # Accept if query is the first word in the name
                first_word = name.split(",")[0].split(" ")[0]
                if first_word == query_lower or query_lower in name.split(",")[0]:
                    filtered.append((name, score, idx))
                elif score >= 85:
                    # High score = probably a good match even if not first word
                    filtered.append((name, score, idx))

            if not filtered:
                filtered = [(name, score, idx) for name, score, idx in results[:3]]

            # Among close matches, prefer shorter names
            best_score = filtered[0][1]
            close_matches = [(name, score, idx) for name, score, idx in filtered
                            if score >= best_score - 10]
            close_matches.sort(key=lambda x: len(x[0]))
            matched_name = close_matches[0][0]
            matched_score = close_matches[0][1]

            logger.debug(
                "Fuzzy match: '%s' → '%s' (score=%d, source=%s)",
                query, matched_name, matched_score, source_label,
            )
            return self._entry_to_nutrition(data[matched_name], source_label)

        return None

    @staticmethod
    def _entry_to_nutrition(entry: dict, source: str) -> NutritionPer100g:
        """Convert a lookup dict entry to NutritionPer100g."""
        return NutritionPer100g(
            kcal=float(entry.get("kcal", 0)),
            protein_g=float(entry.get("protein_g", 0)),
            fat_g=float(entry.get("fat_g", 0)),
            saturated_fat_g=float(entry.get("saturated_fat_g", 0)),
            carbs_g=float(entry.get("carbs_g", 0)),
            fiber_g=float(entry.get("fiber_g", 0)),
            sugar_g=float(entry.get("sugar_g", 0)),
            salt_g=float(entry.get("salt_g", 0)),
            source=source,
        )

    def lookup(self, ingredient_name: str) -> Optional[NutritionPer100g]:
        """
        Look up nutrition data for an ingredient name.

        Priority: CIQUAL → OFF → USDA.
        Normalises the name to EU English before searching.

        Args:
            ingredient_name: Raw ingredient name (e.g. "chicken breast", "eggplant").

        Returns:
            NutritionPer100g if found, None if no source matches.
        """
        self._ensure_loaded()
        self.stats["total"] += 1

        # Normalise to EU English via synonym_resolver
        try:
            from services.synonym_resolver import normalize_ingredient
            normalised = normalize_ingredient(ingredient_name)
        except ImportError:
            normalised = ingredient_name

        # Tier 1: CIQUAL (EU primary)
        result = self._fuzzy_search(normalised, self._ciqual_names, self._ciqual, "ciqual")
        if result:
            self.stats["ciqual_hit"] += 1
            return result

        # Tier 2: Open Food Facts (EU secondary)
        result = self._fuzzy_search(normalised, self._off_names, self._off, "off")
        if result:
            self.stats["off_hit"] += 1
            return result

        # Tier 3: USDA (US fallback)
        result = self._fuzzy_search(normalised, self._usda_names, self._usda, "usda")
        if result:
            self.stats["usda_hit"] += 1
            return result

        self.stats["miss"] += 1
        logger.debug("No nutrition match for '%s' (normalised: '%s')", ingredient_name, normalised)
        return None

    def coverage_rate(self) -> float:
        """Return the percentage of ingredients matched so far."""
        if self.stats["total"] == 0:
            return 0.0
        return (self.stats["total"] - self.stats["miss"]) / self.stats["total"] * 100

    def reset_stats(self) -> None:
        """Reset coverage tracking stats."""
        self.stats = {"total": 0, "ciqual_hit": 0, "off_hit": 0, "usda_hit": 0, "miss": 0}


# Module-level singleton
_instance: NutritionLookup | None = None


def get_nutrition_lookup() -> NutritionLookup:
    """Get or create the singleton NutritionLookup instance."""
    global _instance
    if _instance is None:
        _instance = NutritionLookup()
    return _instance
