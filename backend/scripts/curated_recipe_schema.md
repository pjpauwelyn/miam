# Curated Recipe Output Schema

Each recipe must be a valid JSON object matching this exact structure. All measurements metric. All ingredient names EU/British English (aubergine not eggplant, courgette not zucchini, coriander not cilantro, spring onion not scallion, rocket not arugula, broad bean not fava bean, chickpea not garbanzo, double cream not heavy cream, single cream not light cream, plain flour not all-purpose flour).

```json
{
  "title": "Authentic recipe name",
  "title_en": "English title (same if already English)",
  "cuisine_tags": ["Italian"],
  "region_tag": "Tuscany",
  "description": "100-200 word description for European audience. Mention origin, key techniques, what makes it special.",
  "ingredients": [
    {
      "name": "ingredient in EU English",
      "amount": 200.0,
      "unit": "g",
      "notes": "finely diced",
      "is_optional": false,
      "substitutions": [
        {"substitute": "alternative ingredient", "ratio": "1:1", "notes": "works well in summer"}
      ]
    }
  ],
  "steps": [
    {
      "step_number": 1,
      "instruction": "Clear, actionable instruction with temperatures in Celsius.",
      "duration_min": 5,
      "technique_tags": ["sauté", "deglaze"]
    }
  ],
  "time_prep_min": 20,
  "time_cook_min": 45,
  "time_total_min": 65,
  "serves": 4,
  "difficulty": 3,
  "flavor_tags": ["umami", "herbaceous"],
  "texture_tags": ["creamy", "tender"],
  "dietary_tags": ["vegetarian", "nut-free"],
  "dietary_flags": {
    "is_vegan": false,
    "is_vegetarian": true,
    "is_pescatarian_ok": true,
    "is_dairy_free": false,
    "is_gluten_free": true,
    "is_nut_free": true,
    "is_halal_ok": true,
    "contains_pork": false,
    "contains_shellfish": false,
    "contains_alcohol": false,
    "vegan_if_substituted": true,
    "gluten_free_if_substituted": false
  },
  "nutrition_per_serving": {
    "kcal": 420,
    "protein_g": 18.5,
    "fat_g": 22.0,
    "saturated_fat_g": 8.0,
    "carbs_g": 35.0,
    "fiber_g": 4.5,
    "sugar_g": 6.0,
    "salt_g": 1.2
  },
  "season_tags": ["autumn", "winter"],
  "occasion_tags": ["weeknight", "comfort-food"],
  "course_tags": ["main"],
  "image_placeholder": "A beautifully plated [dish], shot from above on a rustic wooden table with [garnish] and [context].",
  "source_type": "curated-verified",
  "wine_pairing_notes": "A medium-bodied Chianti Classico complements the rich tomato sauce.",
  "tips": [
    "practical cooking tip 1",
    "storage or serving tip 2"
  ]
}
```

## Valid values for fields:
- **unit**: g | ml | dl | cl | tbsp | tsp | piece | bunch | pinch | to-taste | slice | clove | sprig | leaf | stick | sheet
- **difficulty**: 1 (beginner) to 5 (professional)
- **flavor_tags**: umami, acidic, sweet, bitter, spicy, herbaceous, smoky, rich, light, tangy, savoury, floral, earthy, nutty, fresh, pungent, warming, cooling
- **texture_tags**: creamy, crispy, tender, crunchy, silky, chunky, fluffy, chewy, flaky, velvety, firm, crumbly, smooth, gelatinous, snappy
- **season_tags**: spring, summer, autumn, winter, year-round
- **occasion_tags**: weeknight, dinner-party, date-night, christmas, easter, bbq, picnic, comfort-food, meal-prep, brunch, celebration, quick-lunch, packed-lunch
- **course_tags**: starter, main, side, dessert, snack, breakfast, soup, salad, bread
- **source_type**: curated-verified

## Nutrition accuracy
Nutrition values MUST be realistic. Cross-reference with known databases. For example:
- 100g chicken breast ≈ 165 kcal, 31g protein, 3.6g fat
- 100g pasta (cooked) ≈ 131 kcal, 5g protein, 1.1g fat, 25g carbs
- 100g olive oil ≈ 884 kcal, 100g fat
- 1 egg ≈ 78 kcal, 6g protein, 5g fat
