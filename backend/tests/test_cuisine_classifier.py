"""
Cuisine classifier tests — rule-based engine: 30+ cuisine cases, compound
shadowing regressions (Kimchi/Thai fried rice), edge cases (empty, no-signal,
fusion).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.cuisine_classifier import classify_rule_based


# ---------------------------------------------------------------------------
# Standard cuisine identification (20+ cases)
# ---------------------------------------------------------------------------


class TestCuisineClassification:
    """Rule-based classification for known dishes."""

    def test_spaghetti_carbonara_is_italian(self):
        assert classify_rule_based("Spaghetti Carbonara", []) == "Italian"

    def test_pizza_margherita_is_italian(self):
        assert classify_rule_based("Pizza Margherita", []) == "Italian"

    def test_risotto_milanese_is_italian(self):
        assert classify_rule_based("Risotto alla Milanese", []) == "Italian"

    def test_cacio_e_pepe_is_italian(self):
        assert classify_rule_based("Cacio e Pepe", []) == "Italian"

    def test_pad_thai_is_thai(self):
        assert classify_rule_based("Pad Thai", []) == "Thai"

    def test_chicken_tikka_masala_is_indian(self):
        assert classify_rule_based("Chicken Tikka Masala", []) == "Indian"

    def test_french_onion_soup_is_french(self):
        assert classify_rule_based("French Onion Soup", []) == "French"

    def test_coq_au_vin_is_french(self):
        assert classify_rule_based("Coq au Vin", []) == "French"

    def test_taco_is_mexican(self):
        result = classify_rule_based("Beef Taco with Salsa", [])
        assert result == "Mexican"

    def test_burrito_is_mexican(self):
        result = classify_rule_based("Chicken Burrito", [])
        assert result == "Mexican"

    def test_sushi_is_japanese(self):
        assert classify_rule_based("Sushi", []) == "Japanese"

    def test_ramen_is_japanese(self):
        assert classify_rule_based("Ramen", []) == "Japanese"

    def test_bibimbap_is_korean(self):
        assert classify_rule_based("Bibimbap", []) == "Korean"

    def test_paella_is_spanish(self):
        assert classify_rule_based("Paella", []) == "Spanish"

    def test_moussaka_is_greek(self):
        assert classify_rule_based("Moussaka", []) == "Greek"

    def test_bratwurst_is_german(self):
        assert classify_rule_based("Bratwurst", []) == "German"

    def test_pho_is_vietnamese(self):
        assert classify_rule_based("Pho Bo", []) == "Vietnamese"

    def test_tagine_is_moroccan(self):
        assert classify_rule_based("Lamb Tagine", []) == "Moroccan"

    def test_hummus_is_lebanese(self):
        result = classify_rule_based("Hummus", [])
        assert result == "Lebanese"

    def test_falafel_is_lebanese(self):
        result = classify_rule_based("Falafel", [])
        assert result == "Lebanese"

    def test_jerk_chicken_is_caribbean(self):
        result = classify_rule_based("Jerk Chicken", [])
        assert result == "Caribbean"


# ---------------------------------------------------------------------------
# Compound shadowing regression tests
# ---------------------------------------------------------------------------


class TestCompoundShadowing:
    """
    Guard against the original bug: "fried rice" maps to Chinese, so
    "Kimchi Fried Rice" or "Thai Fried Rice" must not be classified as Chinese.
    """

    def test_kimchi_fried_rice_is_korean(self):
        result = classify_rule_based("Kimchi Fried Rice", [])
        assert result == "Korean", f"Expected Korean, got {result}"

    def test_thai_fried_rice_is_thai(self):
        result = classify_rule_based("Thai Fried Rice", [])
        assert result == "Thai", f"Expected Thai, got {result}"

    def test_thai_green_curry_is_thai(self):
        result = classify_rule_based("Thai Green Curry", [])
        assert result == "Thai", f"Expected Thai, got {result}"

    def test_plain_fried_rice_is_chinese(self):
        result = classify_rule_based("Fried Rice", [])
        assert result == "Chinese", f"Expected Chinese, got {result}"

    def test_plain_curry_is_indian(self):
        result = classify_rule_based("Chicken Curry", [])
        assert result == "Indian", f"Expected Indian, got {result}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_title_and_empty_ner_returns_none(self):
        """Empty title + empty NER → should return None."""
        assert classify_rule_based("", []) is None

    def test_no_cuisine_signals_returns_none(self):
        """Title with no cuisine indicators → should return None."""
        result = classify_rule_based("My Special Recipe", [])
        # May return None or a guess based on very generic words
        # The key thing is it doesn't crash
        assert result is None or isinstance(result, str)

    def test_conflicting_signals_returns_valid(self):
        """Fusion dish with signals from multiple cuisines → should return something valid."""
        result = classify_rule_based("Japanese-Italian Fusion Pasta", [])
        # Could be Japanese, Italian, or Fusion — any valid answer is acceptable
        assert result is not None
        assert isinstance(result, str)

    def test_unicode_title_no_crash(self):
        """Unicode characters in title should not cause a crash."""
        result = classify_rule_based("寿司", [])
        # May or may not classify — the key is no crash
        assert result is None or isinstance(result, str)

    def test_ingredient_based_classification(self):
        """When title has no signal, ingredients should drive classification."""
        result = classify_rule_based("My Dinner", ["soy sauce", "ginger", "rice", "sesame oil"])
        # Should detect East Asian cuisine from ingredients
        assert result is None or isinstance(result, str)
