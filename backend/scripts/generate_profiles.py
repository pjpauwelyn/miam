"""
Generate 5 test user profiles for miam Phase 0.

Profiles:
1. Lena — Dutch, adventurous home cook, mostly plant-based, loves Asian flavours
2. Marco — Italian expat in Amsterdam, traditional Italian + French, meat lover
3. Priya — Indian vegetarian, strict no-beef/no-pork, expert-level cook
4. Alex (edge case) — "vegan who eats fish" (pescatarian mislabelled), loves Thai
5. Youssef (stress test) — celiac + nut allergy + halal + beginner cook + 30min max
"""
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from models.personal_ontology import (
    UserProfile,
    DimensionMeta,
    DimensionWeight,
    UpdateSource,
    CookingSkill,
    KitchenSetup,
    NutritionalAwarenessLevel,
    SocialContext,
    InspirationStyle,
    PreferenceLevel,
    TensionSeverity,
    DietaryRestriction,
    DietaryProfile,
    CuisineAffinity,
    CuisineAffinityProfile,
    FlavorProfile,
    TextureProfile,
    KitchenEquipment,
    CookingContext,
    BudgetProfile,
    VibeAffinity,
    DiningVibeProfile,
    AdventurousnessProfile,
    NutritionalProfile,
    SocialProfile,
    LifestyleProfile,
    LocationProfile,
    ProfileTension,
)


def meta(weight: DimensionWeight = DimensionWeight.IMPORTANT, source: UpdateSource = UpdateSource.ONBOARDING):
    return DimensionMeta(weight=weight, update_source=source)


def generate_lena() -> UserProfile:
    """Lena — Dutch adventurous home cook, plant-based, Asian-forward."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            meta=meta(DimensionWeight.CORE),
            spectrum_label="mostly-plant-based",
            hard_stops=[
                DietaryRestriction(label="no-veal", is_hard_stop=True, reason="Ethical"),
                DietaryRestriction(label="no-foie-gras", is_hard_stop=True, reason="Ethical"),
            ],
            soft_stops=[
                DietaryRestriction(label="reduce-meat", is_hard_stop=False, reason="Flexitarian — eats fish occasionally"),
            ],
            nuance_notes="Prefers sustainable sourcing. Flexitarian leaning plant-based.",
        ),
        cuisine_affinities=CuisineAffinityProfile(
            meta=meta(DimensionWeight.CORE),
            affinities=[
                CuisineAffinity(cuisine="Japanese", level=PreferenceLevel.LOVE, confidence=0.95),
                CuisineAffinity(cuisine="Thai", level=PreferenceLevel.LOVE, confidence=0.90),
                CuisineAffinity(cuisine="Dutch", level=PreferenceLevel.LIKE, confidence=0.80),
                CuisineAffinity(cuisine="Indian", level=PreferenceLevel.LIKE, confidence=0.85),
                CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LIKE, confidence=0.75),
                CuisineAffinity(cuisine="French", level=PreferenceLevel.NEUTRAL, confidence=0.60),
            ],
        ),
        flavor=FlavorProfile(
            meta=meta(),
            spicy=7.0, sweet=3.0, sour=6.0, umami=9.0, bitter=4.0,
            fatty=5.0, fermented=7.0, smoky=5.0, salty=6.0,
        ),
        texture=TextureProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            crunchy=8.0, creamy=5.0, soft=4.0, chewy=3.0,
            crispy=9.0, silky=6.0, chunky=5.0,
        ),
        cooking=CookingContext(
            meta=meta(),
            skill=CookingSkill.ADVANCED,
            kitchen_setup=KitchenSetup.FULLY_EQUIPPED,
            specific_equipment=KitchenEquipment(
                wok=True, food_processor=True, cast_iron=True, pressure_cooker=True,
            ),
            weeknight_minutes=45,
            weekend_minutes=120,
        ),
        budget=BudgetProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            home_per_meal_eur=12.0,
            out_per_meal_eur=45.0,
        ),
        dining_vibe=DiningVibeProfile(
            meta=meta(),
            vibes=[
                VibeAffinity(vibe="casual", score=9.0),
                VibeAffinity(vibe="cozy", score=8.5),
                VibeAffinity(vibe="trendy", score=7.0),
                VibeAffinity(vibe="outdoor-terrace", score=8.0),
            ],
        ),
        adventurousness=AdventurousnessProfile(
            meta=meta(),
            cooking_score=8.5,
            dining_score=8.0,
        ),
        nutrition=NutritionalProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            level=NutritionalAwarenessLevel.LIGHT,
        ),
        social=SocialProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            default_social_context=SocialContext.COUPLE,
            meals_out_per_week=2.0,
            home_cooked_per_week=5.0,
        ),
        lifestyle=LifestyleProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            seasonal_preference_score=8.0,
            sustainability_priority_score=7.0,
            inspiration_style=InspirationStyle.WIDE_SELECTION,
        ),
        location=LocationProfile(
            meta=meta(),
            city="Amsterdam",
            country="NL",
            radius_km=5.0,
        ),
        profile_summary_text="Lena is an adventurous Dutch home cook who leans plant-based. She loves Japanese and Thai flavours, has a well-equipped kitchen with a wok and cast iron, and enjoys discovering new cuisines from farmers' markets and food blogs.",
        onboarding_complete=True,
    )


def generate_marco() -> UserProfile:
    """Marco — Italian expat, traditional, meat lover."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            spectrum_label="omnivore",
            nuance_notes="No dietary restrictions. Enjoys all types of meat and seafood.",
        ),
        cuisine_affinities=CuisineAffinityProfile(
            meta=meta(DimensionWeight.CORE),
            affinities=[
                CuisineAffinity(cuisine="Italian", level=PreferenceLevel.LOVE, confidence=0.98),
                CuisineAffinity(cuisine="French", level=PreferenceLevel.LIKE, confidence=0.85),
                CuisineAffinity(cuisine="Spanish", level=PreferenceLevel.LIKE, confidence=0.75),
                CuisineAffinity(cuisine="Dutch", level=PreferenceLevel.NEUTRAL, confidence=0.40),
            ],
        ),
        flavor=FlavorProfile(
            meta=meta(),
            spicy=2.0, sweet=4.0, sour=6.0, umami=8.0, bitter=5.0,
            fatty=7.0, fermented=3.0, smoky=4.0, salty=6.0,
        ),
        texture=TextureProfile(
            meta=meta(),
            crunchy=6.0, creamy=8.0, soft=7.0, chewy=2.0,
            crispy=7.0, silky=6.0, chunky=4.0,
        ),
        cooking=CookingContext(
            meta=meta(),
            skill=CookingSkill.PROFESSIONAL,
            kitchen_setup=KitchenSetup.FULLY_EQUIPPED,
            specific_equipment=KitchenEquipment(
                pasta_machine=True, cast_iron=True, stand_mixer=True,
            ),
            weeknight_minutes=60,
            weekend_minutes=180,
        ),
        budget=BudgetProfile(
            meta=meta(),
            home_per_meal_eur=15.0,
            out_per_meal_eur=60.0,
        ),
        dining_vibe=DiningVibeProfile(
            meta=meta(),
            vibes=[
                VibeAffinity(vibe="romantic", score=9.0),
                VibeAffinity(vibe="traditional", score=8.5),
                VibeAffinity(vibe="upscale", score=7.0),
            ],
        ),
        adventurousness=AdventurousnessProfile(
            meta=meta(),
            cooking_score=4.0,
            dining_score=3.5,
        ),
        nutrition=NutritionalProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            level=NutritionalAwarenessLevel.NONE,
        ),
        social=SocialProfile(
            meta=meta(),
            default_social_context=SocialContext.COUPLE,
            meals_out_per_week=3.0,
            home_cooked_per_week=5.0,
        ),
        lifestyle=LifestyleProfile(
            meta=meta(),
            seasonal_preference_score=9.0,
            sustainability_priority_score=4.0,
            inspiration_style=InspirationStyle.ONE_BEST,
        ),
        location=LocationProfile(
            meta=meta(),
            city="Amsterdam",
            country="NL",
            radius_km=3.0,
        ),
        profile_summary_text="Marco is an Italian expat and professional-level cook who values tradition. He favours Italian and French cuisine, uses a pasta machine regularly, and prefers romantic upscale dining experiences.",
        onboarding_complete=True,
    )


def generate_priya() -> UserProfile:
    """Priya — Indian vegetarian, strict restrictions, expert cook."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            meta=meta(DimensionWeight.CORE),
            spectrum_label="vegetarian",
            hard_stops=[
                DietaryRestriction(label="no-beef", is_hard_stop=True, reason="Religious — Hindu"),
                DietaryRestriction(label="no-pork", is_hard_stop=True, reason="Religious — Hindu"),
                DietaryRestriction(label="no-gelatin", is_hard_stop=True, reason="Vegetarian"),
                DietaryRestriction(label="no-lard", is_hard_stop=True, reason="Vegetarian"),
                DietaryRestriction(label="no-rennet", is_hard_stop=True, reason="Vegetarian"),
            ],
            soft_stops=[],
            nuance_notes="Hindu — lifelong strict vegetarian. No beef or pork ever. Family recipes from Kerala and Gujarat.",
        ),
        cuisine_affinities=CuisineAffinityProfile(
            meta=meta(DimensionWeight.CORE),
            affinities=[
                CuisineAffinity(cuisine="Indian", level=PreferenceLevel.LOVE, confidence=0.98),
                CuisineAffinity(cuisine="Middle Eastern", level=PreferenceLevel.LIKE, confidence=0.80),
                CuisineAffinity(cuisine="Thai", level=PreferenceLevel.LIKE, confidence=0.75),
                CuisineAffinity(cuisine="Italian", level=PreferenceLevel.NEUTRAL, confidence=0.65),
            ],
        ),
        flavor=FlavorProfile(
            meta=meta(DimensionWeight.CORE),
            spicy=9.5, sweet=6.0, sour=7.0, umami=8.0, bitter=4.0,
            fatty=5.0, fermented=6.0, smoky=3.0, salty=5.0,
        ),
        texture=TextureProfile(
            meta=meta(),
            crunchy=7.0, creamy=8.0, soft=7.0, chewy=4.0,
            crispy=6.0, silky=5.0, chunky=5.0,
        ),
        cooking=CookingContext(
            meta=meta(),
            skill=CookingSkill.PROFESSIONAL,
            kitchen_setup=KitchenSetup.FULLY_EQUIPPED,
            specific_equipment=KitchenEquipment(
                pressure_cooker=True, food_processor=True,
            ),
            weeknight_minutes=45,
            weekend_minutes=150,
        ),
        budget=BudgetProfile(
            meta=meta(),
            home_per_meal_eur=8.0,
            out_per_meal_eur=30.0,
        ),
        dining_vibe=DiningVibeProfile(
            meta=meta(),
            vibes=[
                VibeAffinity(vibe="casual", score=8.5),
                VibeAffinity(vibe="family-friendly", score=9.0),
                VibeAffinity(vibe="authentic", score=9.5),
            ],
        ),
        adventurousness=AdventurousnessProfile(
            meta=meta(),
            cooking_score=7.0,
            dining_score=6.0,
        ),
        nutrition=NutritionalProfile(
            meta=meta(),
            level=NutritionalAwarenessLevel.STRICT,
            tracked_dimensions=["protein", "iron"],
        ),
        social=SocialProfile(
            meta=meta(),
            default_social_context=SocialContext.FAMILY,
            meals_out_per_week=1.5,
            home_cooked_per_week=6.0,
        ),
        lifestyle=LifestyleProfile(
            meta=meta(),
            seasonal_preference_score=7.0,
            sustainability_priority_score=6.0,
            inspiration_style=InspirationStyle.ONE_BEST,
        ),
        location=LocationProfile(
            meta=meta(),
            city="Amsterdam",
            country="NL",
            radius_km=5.0,
        ),
        profile_summary_text="Priya is a professional-level vegetarian cook from India, strict about no beef/pork/gelatin. Loves spicy, aromatic dishes. Family-oriented dining, prefers authentic casual spots.",
        onboarding_complete=True,
    )


def generate_edge_case() -> UserProfile:
    """Edge case — vegan-who-eats-fish (pescatarian mislabelled as vegan), Thai lover."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            meta=meta(DimensionWeight.CORE),
            spectrum_label="vegan",  # Self-labelled vegan but eats fish — should trigger tension
            hard_stops=[
                DietaryRestriction(label="no-meat", is_hard_stop=True, reason="Environmental"),
                DietaryRestriction(label="no-dairy", is_hard_stop=True, reason="Environmental"),
                DietaryRestriction(label="no-eggs", is_hard_stop=True, reason="Environmental"),
            ],
            soft_stops=[
                DietaryRestriction(label="fish-ok", is_hard_stop=False, reason="Sustainable fish is acceptable"),
            ],
            nuance_notes="Self-identifies as vegan but eats sustainably sourced fish. Tree nut allergy.",
        ),
        cuisine_affinities=CuisineAffinityProfile(
            meta=meta(DimensionWeight.CORE),
            affinities=[
                CuisineAffinity(cuisine="Thai", level=PreferenceLevel.LOVE, confidence=0.95),
                CuisineAffinity(cuisine="Japanese", level=PreferenceLevel.LIKE, confidence=0.85),
                CuisineAffinity(cuisine="Vietnamese", level=PreferenceLevel.LIKE, confidence=0.80),
            ],
        ),
        flavor=FlavorProfile(
            meta=meta(),
            spicy=8.5, sweet=2.0, sour=7.0, umami=7.0, bitter=3.0,
            fatty=2.0, fermented=5.0, smoky=3.0, salty=5.0,
        ),
        texture=TextureProfile(
            meta=meta(),
            crunchy=8.0, creamy=4.0, soft=5.0, chewy=3.0,
            crispy=7.0, silky=6.0, chunky=4.0,
        ),
        cooking=CookingContext(
            meta=meta(),
            skill=CookingSkill.CONFIDENT,
            kitchen_setup=KitchenSetup.WELL_EQUIPPED,
            specific_equipment=KitchenEquipment(wok=True),
            weeknight_minutes=30,
            weekend_minutes=90,
        ),
        budget=BudgetProfile(
            meta=meta(),
            home_per_meal_eur=8.0,
            out_per_meal_eur=25.0,
        ),
        dining_vibe=DiningVibeProfile(
            meta=meta(),
            vibes=[
                VibeAffinity(vibe="casual", score=9.0),
                VibeAffinity(vibe="hole-in-the-wall", score=8.5),
            ],
        ),
        adventurousness=AdventurousnessProfile(
            meta=meta(),
            cooking_score=7.5,
            dining_score=7.0,
        ),
        nutrition=NutritionalProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            level=NutritionalAwarenessLevel.LIGHT,
        ),
        social=SocialProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            default_social_context=SocialContext.COUPLE,
            meals_out_per_week=2.0,
            home_cooked_per_week=5.0,
        ),
        lifestyle=LifestyleProfile(
            meta=meta(DimensionWeight.OPTIONAL),
            seasonal_preference_score=6.0,
            sustainability_priority_score=8.0,
            inspiration_style=InspirationStyle.SHORT_LIST,
        ),
        location=LocationProfile(
            meta=meta(),
            city="Amsterdam",
            country="NL",
            radius_km=4.0,
        ),
        profile_summary_text="Alex self-identifies as vegan but eats sustainably sourced fish — a contradiction the system should detect. Loves Thai food and casual hole-in-the-wall spots. Tree nut allergy.",
        onboarding_complete=True,
    )


def generate_stress_test() -> UserProfile:
    """Stress test — maximum constraints: celiac + nut allergy + halal + beginner + 30min."""
    return UserProfile(
        user_id=uuid4(),
        dietary=DietaryProfile(
            meta=meta(DimensionWeight.CORE),
            spectrum_label="halal",
            hard_stops=[
                DietaryRestriction(label="halal-only", is_hard_stop=True, reason="Religious — strictly halal"),
                DietaryRestriction(label="gluten-free", is_hard_stop=True, reason="Diagnosed celiac disease"),
                DietaryRestriction(label="no-pork", is_hard_stop=True, reason="Halal"),
                DietaryRestriction(label="no-alcohol", is_hard_stop=True, reason="Halal — no alcohol in cooking"),
                DietaryRestriction(label="no-peanuts", is_hard_stop=True, reason="Severe allergy"),
                DietaryRestriction(label="no-tree-nuts", is_hard_stop=True, reason="Severe allergy"),
                DietaryRestriction(label="no-sesame", is_hard_stop=True, reason="Allergy"),
                DietaryRestriction(label="no-gelatin", is_hard_stop=True, reason="Halal — non-halal gelatin"),
            ],
            soft_stops=[],
            nuance_notes="Strictly halal. Diagnosed celiac — no gluten. Severe peanut and tree nut allergy. Sesame allergy. No alcohol in cooking.",
        ),
        cuisine_affinities=CuisineAffinityProfile(
            meta=meta(),
            affinities=[
                CuisineAffinity(cuisine="Middle Eastern", level=PreferenceLevel.LOVE, confidence=0.90),
                CuisineAffinity(cuisine="North African", level=PreferenceLevel.LIKE, confidence=0.85),
                CuisineAffinity(cuisine="Turkish", level=PreferenceLevel.LIKE, confidence=0.80),
                CuisineAffinity(cuisine="Dutch", level=PreferenceLevel.NEUTRAL, confidence=0.50),
            ],
        ),
        flavor=FlavorProfile(
            meta=meta(),
            spicy=5.0, sweet=5.0, sour=3.0, umami=6.0, bitter=2.0,
            fatty=4.0, fermented=2.0, smoky=4.0, salty=5.0,
        ),
        texture=TextureProfile(
            meta=meta(),
            crunchy=6.0, creamy=5.0, soft=7.0, chewy=2.0,
            crispy=7.0, silky=4.0, chunky=5.0,
        ),
        cooking=CookingContext(
            meta=meta(DimensionWeight.CORE),
            skill=CookingSkill.BEGINNER,
            kitchen_setup=KitchenSetup.BASIC,
            specific_equipment=KitchenEquipment(),
            weeknight_minutes=20,
            weekend_minutes=45,
        ),
        budget=BudgetProfile(
            meta=meta(DimensionWeight.CORE),
            home_per_meal_eur=6.0,
            out_per_meal_eur=20.0,
        ),
        dining_vibe=DiningVibeProfile(
            meta=meta(),
            vibes=[
                VibeAffinity(vibe="casual", score=9.0),
                VibeAffinity(vibe="quick-service", score=8.0),
                VibeAffinity(vibe="family-friendly", score=8.5),
            ],
        ),
        adventurousness=AdventurousnessProfile(
            meta=meta(),
            cooking_score=3.0,
            dining_score=3.5,
        ),
        nutrition=NutritionalProfile(
            meta=meta(DimensionWeight.CORE),
            level=NutritionalAwarenessLevel.STRICT,
            tracked_dimensions=["protein", "carbs"],
        ),
        social=SocialProfile(
            meta=meta(),
            default_social_context=SocialContext.SOLO,
            meals_out_per_week=1.0,
            home_cooked_per_week=6.0,
        ),
        lifestyle=LifestyleProfile(
            meta=meta(),
            seasonal_preference_score=4.0,
            sustainability_priority_score=3.0,
            inspiration_style=InspirationStyle.SHORT_LIST,
        ),
        location=LocationProfile(
            meta=meta(),
            city="Amsterdam",
            country="NL",
            radius_km=3.0,
        ),
        profile_summary_text="Youssef has the most constrained profile: halal + celiac + nut/sesame allergies + beginner cook with only basic equipment and a 20-minute weeknight budget. This profile stress-tests the retrieval and refinement pipeline.",
        onboarding_complete=True,
    )


def main():
    output_dir = Path(__file__).resolve().parents[1] / "data" / "profiles"
    output_dir.mkdir(parents=True, exist_ok=True)

    generators = {
        "lena": generate_lena,
        "marco": generate_marco,
        "priya": generate_priya,
        "alex_edge_case": generate_edge_case,
        "youssef_stress_test": generate_stress_test,
    }

    profiles = []
    for name, gen_fn in generators.items():
        profile = gen_fn()
        profile_dict = profile.model_dump(mode="json")

        filepath = output_dir / f"{name}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(profile_dict, f, indent=2, default=str)

        profiles.append(profile_dict)
        print(f"Generated profile: {name} (user_id={profile.user_id})")
        print(f"  Dietary: {profile.dietary.spectrum_label}")
        print(f"  Skill: {profile.cooking.skill.value}")
        top_cuisine = profile.cuisine_affinities.affinities[0].cuisine if profile.cuisine_affinities.affinities else "none"
        print(f"  Top cuisine: {top_cuisine}")
        print(f"  Tensions: {len(profile.tensions)}")
        if profile.tensions:
            for t in profile.tensions:
                print(f"    - [{t.severity.value}] {t.description}")
        print()

    all_path = output_dir / "all_profiles.json"
    with open(all_path, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, default=str)

    print(f"All {len(profiles)} profiles saved to {all_path}")


if __name__ == "__main__":
    main()
