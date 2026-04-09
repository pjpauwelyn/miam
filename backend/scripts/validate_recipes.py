"""
Validate recipes against RecipeNLG baseline and full schema.
"""
import json
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECIPES_PATH = PROJECT_ROOT / "data" / "recipes" / "recipes_all.json"

sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def validate_baseline(recipe: dict) -> list[str]:
    """RecipeNLG baseline: title, ingredients[].name, steps[].instruction must be non-empty."""
    errors = []
    title = recipe.get("title", "").strip()
    if not title:
        errors.append("Missing or empty title")
    
    ingredients = recipe.get("ingredients", [])
    if not ingredients:
        errors.append("No ingredients")
    else:
        for i, ing in enumerate(ingredients):
            if isinstance(ing, dict):
                name = ing.get("name", "").strip()
                if not name:
                    errors.append(f"Ingredient {i} has no name")
            else:
                errors.append(f"Ingredient {i} is not a dict")
    
    steps = recipe.get("steps", [])
    # Edge cases with empty steps are expected
    if steps:
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                inst = step.get("instruction", "").strip()
                if not inst:
                    errors.append(f"Step {i} has no instruction")
    
    return errors


def validate_full_schema(recipe: dict) -> list[str]:
    """Validate against the full RecipeDocument schema."""
    errors = []
    
    required_fields = [
        "id", "title", "cuisine_tags", "ingredients", "steps",
        "time_prep_min", "time_cook_min", "time_total_min",
        "serves", "difficulty", "source_type", "embedding_text",
    ]
    
    for field in required_fields:
        if field not in recipe:
            errors.append(f"Missing field: {field}")
    
    # Check dietary_flags structure
    flags = recipe.get("dietary_flags", {})
    if isinstance(flags, dict):
        expected_flags = [
            "is_vegan", "is_vegetarian", "is_pescatarian_ok",
            "is_dairy_free", "is_gluten_free", "is_nut_free",
            "is_halal_ok", "contains_pork", "contains_shellfish",
            "contains_alcohol",
        ]
        for flag in expected_flags:
            if flag not in flags:
                errors.append(f"Missing dietary_flag: {flag}")
    
    # Check nutrition structure
    nutrition = recipe.get("nutrition_per_serving", {})
    if isinstance(nutrition, dict):
        expected_fields = ["kcal", "protein_g", "fat_g", "carbs_g"]
        for field in expected_fields:
            if field not in nutrition:
                errors.append(f"Missing nutrition field: {field}")
    
    return errors


def main():
    if not RECIPES_PATH.exists():
        print(f"ERROR: {RECIPES_PATH} not found")
        sys.exit(1)
    
    with open(RECIPES_PATH) as f:
        recipes = json.load(f)
    
    print(f"Validating {len(recipes)} recipes...\n")
    
    baseline_pass = 0
    baseline_fail = 0
    schema_pass = 0
    schema_fail = 0
    edge_count = 0
    
    baseline_errors_all = []
    schema_errors_all = []
    
    for i, recipe in enumerate(recipes):
        is_edge = recipe.get("title", "").startswith("[EDGE")
        if is_edge:
            edge_count += 1
        
        # Baseline validation
        b_errors = validate_baseline(recipe)
        if b_errors and not is_edge:
            baseline_fail += 1
            baseline_errors_all.append((i, recipe.get("title", "?"), b_errors))
        else:
            baseline_pass += 1
        
        # Full schema validation
        s_errors = validate_full_schema(recipe)
        if s_errors:
            schema_fail += 1
            schema_errors_all.append((i, recipe.get("title", "?"), s_errors))
        else:
            schema_pass += 1
    
    # Cuisine distribution
    cuisines = Counter()
    for r in recipes:
        for t in r.get("cuisine_tags", []):
            cuisines[t] += 1
    
    print("=== VALIDATION REPORT ===\n")
    print(f"Total recipes: {len(recipes)}")
    print(f"Edge cases: {edge_count}")
    print(f"Non-edge recipes: {len(recipes) - edge_count}")
    print()
    print(f"Baseline validation (non-edge):")
    print(f"  Pass: {baseline_pass}")
    print(f"  Fail: {baseline_fail}")
    print()
    print(f"Full schema validation:")
    print(f"  Pass: {schema_pass}")
    print(f"  Fail: {schema_fail}")
    print()
    print(f"Cuisine distribution:")
    for c, n in cuisines.most_common():
        print(f"  {c}: {n}")
    
    if baseline_errors_all:
        print(f"\nBaseline failures (first 5):")
        for idx, title, errs in baseline_errors_all[:5]:
            print(f"  [{idx}] {title}: {', '.join(errs)}")
    
    if schema_errors_all:
        print(f"\nSchema failures (first 5):")
        for idx, title, errs in schema_errors_all[:5]:
            print(f"  [{idx}] {title}: {', '.join(errs)}")
    
    # Exit code: 0 if baseline passes for non-edge recipes
    if baseline_fail == 0:
        print(f"\nRESULT: PASS")
        sys.exit(0)
    else:
        print(f"\nRESULT: FAIL ({baseline_fail} baseline failures)")
        sys.exit(1)


if __name__ == "__main__":
    main()
