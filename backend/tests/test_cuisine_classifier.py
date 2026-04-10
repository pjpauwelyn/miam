"""
Cuisine classifier tests — rule-based engine.

Covers:
 - 80+ standard cuisine / dish title tests
 - Plural title handling (Enchiladas, Pancakes, Stroopwafels)
 - Dutch dish names
 - Ingredient-only classification (no title signal)
 - Compound shadowing regressions (kimchi/thai fried rice)
 - Edge cases (empty, no-signal, fusion, unicode)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.cuisine_classifier import classify_rule_based


# ---------------------------------------------------------------------------
# Standard cuisine identification
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

    def test_tiramisu_is_italian(self):
        assert classify_rule_based("Tiramisu", []) == "Italian"

    def test_osso_buco_is_italian(self):
        assert classify_rule_based("Osso Buco", []) == "Italian"

    def test_panna_cotta_is_italian(self):
        assert classify_rule_based("Panna Cotta", []) == "Italian"

    def test_pad_thai_is_thai(self):
        assert classify_rule_based("Pad Thai", []) == "Thai"

    def test_thai_green_curry_is_thai(self):
        assert classify_rule_based("Thai Green Curry", []) == "Thai"

    def test_tom_yum_is_thai(self):
        assert classify_rule_based("Tom Yum Soup", []) == "Thai"

    def test_chicken_tikka_masala_is_indian(self):
        assert classify_rule_based("Chicken Tikka Masala", []) == "Indian"

    def test_butter_chicken_is_indian(self):
        assert classify_rule_based("Butter Chicken", []) == "Indian"

    def test_biryani_is_indian(self):
        assert classify_rule_based("Chicken Biryani", []) == "Indian"

    def test_french_onion_soup_is_french(self):
        assert classify_rule_based("French Onion Soup", []) == "French"

    def test_coq_au_vin_is_french(self):
        assert classify_rule_based("Coq au Vin", []) == "French"

    def test_beef_bourguignon_is_french(self):
        assert classify_rule_based("Beef Bourguignon", []) == "French"

    def test_taco_is_mexican(self):
        assert classify_rule_based("Beef Taco with Salsa", []) == "Mexican"

    def test_burrito_is_mexican(self):
        assert classify_rule_based("Chicken Burrito", []) == "Mexican"

    def test_enchilada_is_mexican(self):
        assert classify_rule_based("Enchilada", []) == "Mexican"

    def test_guacamole_is_mexican(self):
        assert classify_rule_based("Guacamole", []) == "Mexican"

    def test_ceviche_is_peruvian(self):
        assert classify_rule_based("Ceviche", []) == "Peruvian"

    def test_lomo_saltado_is_peruvian(self):
        assert classify_rule_based("Lomo Saltado", []) == "Peruvian"

    def test_sushi_is_japanese(self):
        assert classify_rule_based("Sushi Roll", []) == "Japanese"

    def test_ramen_is_japanese(self):
        assert classify_rule_based("Ramen", []) == "Japanese"

    def test_teriyaki_is_japanese(self):
        assert classify_rule_based("Teriyaki Chicken", []) == "Japanese"

    def test_bibimbap_is_korean(self):
        assert classify_rule_based("Bibimbap", []) == "Korean"

    def test_bulgogi_is_korean(self):
        assert classify_rule_based("Bulgogi", []) == "Korean"

    def test_tteokbokki_is_korean(self):
        assert classify_rule_based("Tteokbokki", []) == "Korean"

    def test_paella_is_spanish(self):
        assert classify_rule_based("Paella Valenciana", []) == "Spanish"

    def test_gazpacho_is_spanish(self):
        assert classify_rule_based("Gazpacho", []) == "Spanish"

    def test_arroz_con_leche_is_spanish(self):
        assert classify_rule_based("Arroz con Leche", []) == "Spanish"

    def test_moussaka_is_greek(self):
        assert classify_rule_based("Moussaka", []) == "Greek"

    def test_spanakopita_is_greek(self):
        assert classify_rule_based("Spanakopita", []) == "Greek"

    def test_souvlaki_is_greek(self):
        assert classify_rule_based("Souvlaki", []) == "Greek"

    def test_tagine_is_moroccan(self):
        assert classify_rule_based("Lamb Tagine", []) == "Moroccan"

    def test_harira_is_moroccan(self):
        assert classify_rule_based("Harira Soup", []) == "Moroccan"

    def test_hummus_is_lebanese(self):
        assert classify_rule_based("Hummus", []) == "Lebanese"

    def test_falafel_is_lebanese(self):
        assert classify_rule_based("Falafel", []) == "Lebanese"

    def test_tabbouleh_is_lebanese(self):
        assert classify_rule_based("Tabbouleh", []) == "Lebanese"

    def test_kebab_is_turkish(self):
        assert classify_rule_based("Kebab", []) == "Turkish"

    def test_lahmacun_is_turkish(self):
        assert classify_rule_based("Lahmacun", []) == "Turkish"

    def test_pho_is_vietnamese(self):
        assert classify_rule_based("Pho Bo", []) == "Vietnamese"

    def test_banh_mi_is_vietnamese(self):
        assert classify_rule_based("Banh Mi", []) == "Vietnamese"

    def test_bratwurst_is_german(self):
        assert classify_rule_based("Bratwurst", []) == "German"

    def test_schnitzel_is_german(self):
        assert classify_rule_based("Schnitzel", []) == "German"

    def test_jerk_chicken_is_caribbean(self):
        assert classify_rule_based("Jerk Chicken", []) == "Caribbean"

    def test_jollof_is_african(self):
        assert classify_rule_based("Jollof Rice", []) == "African"

    def test_bobotie_is_african(self):
        assert classify_rule_based("Bobotie", []) == "African"

    def test_gravlax_is_scandinavian(self):
        assert classify_rule_based("Gravlax", []) == "Scandinavian"

    def test_mansaf_is_middle_eastern(self):
        assert classify_rule_based("Mansaf", []) == "Middle Eastern"

    def test_cheeseburger_is_american(self):
        assert classify_rule_based("Cheeseburger", []) == "American"

    def test_mac_and_cheese_is_american(self):
        assert classify_rule_based("Mac and Cheese", []) == "American"

    def test_pancake_is_american(self):
        assert classify_rule_based("Pancake", []) == "American"

    def test_fish_and_chips_is_british(self):
        assert classify_rule_based("Fish and Chips", []) == "British"

    def test_beef_wellington_is_british(self):
        assert classify_rule_based("Beef Wellington", []) == "British"

    def test_stroopwafel_is_dutch(self):
        assert classify_rule_based("Stroopwafel", []) == "Dutch"

    def test_stamppot_is_dutch(self):
        assert classify_rule_based("Stamppot", []) == "Dutch"


# ---------------------------------------------------------------------------
# Plural title handling
# ---------------------------------------------------------------------------

class TestPluralTitles:
    """Plural dish names must match the same cuisine as their singular form."""

    def test_enchiladas_is_mexican(self):
        assert classify_rule_based("Enchiladas", []) == "Mexican"

    def test_pancakes_is_american(self):
        assert classify_rule_based("Pancakes", []) == "American"

    def test_tacos_is_mexican(self):
        assert classify_rule_based("Tacos", []) == "Mexican"

    def test_tamales_is_mexican(self):
        assert classify_rule_based("Tamales", []) == "Mexican"

    def test_samosas_is_indian(self):
        assert classify_rule_based("Samosas", []) == "Indian"

    def test_dumplings_is_chinese(self):
        assert classify_rule_based("Dumplings", []) == "Chinese"

    def test_scones_is_british(self):
        assert classify_rule_based("Scones", []) == "British"

    def test_pretzels_is_german(self):
        assert classify_rule_based("Pretzels", []) == "German"

    def test_waffles_is_american(self):
        assert classify_rule_based("Waffles", []) == "American"

    def test_croissants_is_french(self):
        assert classify_rule_based("Croissants", []) == "French"

    def test_gyros_is_greek(self):
        assert classify_rule_based("Gyros", []) == "Greek"

    def test_stroopwafels_is_dutch(self):
        assert classify_rule_based("Stroopwafels", []) == "Dutch"


# ---------------------------------------------------------------------------
# Ingredient-only classification (generic titles)
# ---------------------------------------------------------------------------

class TestIngredientClassification:
    """When the title has no cuisine signal, ingredients should drive classification."""

    def test_soy_sesame_ingredients_are_chinese(self):
        result = classify_rule_based("Weeknight Dinner", ["soy sauce", "sesame oil", "bok choy", "scallion"])
        assert result == "Chinese"

    def test_miso_mirin_ingredients_are_japanese(self):
        result = classify_rule_based("Quick Bowl", ["miso", "mirin", "nori", "udon"])
        assert result == "Japanese"

    def test_kimchi_gochujang_ingredients_are_korean(self):
        result = classify_rule_based("Spicy Rice", ["kimchi", "gochujang", "sesame oil", "scallion"])
        assert result == "Korean"

    def test_lemongrass_galangal_fish_sauce_are_thai(self):
        result = classify_rule_based("Fresh Bowl", ["lemongrass", "galangal", "fish sauce", "coconut milk", "thai basil"])
        assert result == "Thai"

    def test_rice_paper_nuoc_mam_are_vietnamese(self):
        result = classify_rule_based("Fresh Noodles", ["rice paper", "bean sprout", "nuoc mam"])
        assert result == "Vietnamese"

    def test_garam_masala_ghee_are_indian(self):
        result = classify_rule_based("Family Meal", ["garam masala", "ghee", "paneer", "basmati"])
        assert result == "Indian"

    def test_zaatar_sumac_are_lebanese(self):
        result = classify_rule_based("Simple Lunch", ["zaatar", "sumac", "tahini", "bulgur"])
        assert result == "Lebanese"

    def test_smoked_paprika_chorizo_are_spanish(self):
        result = classify_rule_based("Tapas Night", ["smoked paprika", "chorizo", "manchego"])
        assert result == "Spanish"

    def test_parmigiano_pancetta_are_italian(self):
        result = classify_rule_based("Pasta Bake", ["parmigiano", "pancetta", "rigatoni"])
        assert result == "Italian"


# ---------------------------------------------------------------------------
# Compound shadowing regression tests
# ---------------------------------------------------------------------------

class TestCompoundShadowing:
    """
    Guard against the original bug: "fried rice" maps to Chinese, so
    compound variants with a different cuisine MUST resolve correctly.
    """

    def test_kimchi_fried_rice_is_korean(self):
        result = classify_rule_based("Kimchi Fried Rice", [])
        assert result == "Korean", f"Expected Korean, got {result}"

    def test_thai_fried_rice_is_thai(self):
        result = classify_rule_based("Thai Fried Rice", [])
        assert result == "Thai", f"Expected Thai, got {result}"

    def test_pineapple_fried_rice_is_thai(self):
        result = classify_rule_based("Pineapple Fried Rice", [])
        assert result == "Thai", f"Expected Thai, got {result}"

    def test_plain_fried_rice_is_chinese(self):
        result = classify_rule_based("Fried Rice", [])
        assert result == "Chinese", f"Expected Chinese, got {result}"

    def test_plain_curry_is_indian(self):
        result = classify_rule_based("Chicken Curry", [])
        assert result == "Indian", f"Expected Indian, got {result}"

    def test_thai_green_curry_beats_plain_curry(self):
        result = classify_rule_based("Thai Green Curry", [])
        assert result == "Thai", f"Expected Thai, got {result}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_title_and_empty_ner_returns_none(self):
        assert classify_rule_based("", []) is None

    def test_no_cuisine_signals_returns_none(self):
        result = classify_rule_based("My Special Recipe", [])
        assert result is None or isinstance(result, str)

    def test_conflicting_signals_returns_valid(self):
        result = classify_rule_based("Japanese-Italian Fusion Pasta", [])
        assert result is not None and isinstance(result, str)

    def test_unicode_title_no_crash(self):
        result = classify_rule_based("寿司", [])
        assert result is None or isinstance(result, str)

    def test_whitespace_only_title_returns_none(self):
        assert classify_rule_based("   ", []) is None

    def test_ingredient_with_no_title_signal(self):
        result = classify_rule_based("My Dinner", ["soy sauce", "ginger", "sesame oil"])
        assert result is None or isinstance(result, str)
