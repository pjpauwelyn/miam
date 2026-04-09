# Free Recipe Data Source Audit
**Purpose:** Evaluate free/open-source recipe datasets for use in a food recommendation RAG pipeline.  
**Date:** 2026-04-08  
**Audited by:** Research subagent

---

## Executive Summary

No single free dataset satisfies all required fields out of the box. The most viable approach is a **layered strategy**:

1. **Core corpus** — RecipeNLG (2.2M) or Food.com/Kaggle (500K) for scale and ingredient coverage
2. **Structured nutrition** — USDA FoodData Central (CC0) to enrich ingredients → nutrition per serving via NER + lookup
3. **Cuisine + dietary labeling** — TheMealDB (area/category), RecipeDB (26 geo-regions, dietary styles), and datahive/recipes-with-nutrition (health/dietary labels) as reference or seed data
4. **Flavor/texture/occasion tags** — Must be inferred/generated; no free dataset provides flavor_tags, texture_tags, or season_tags natively

---

## Required Field Coverage Shorthand

| Symbol | Meaning |
|--------|---------|
| ✅ | Field present natively and well-populated |
| 🟡 | Field present but incomplete, inconsistent, or requires parsing |
| ❌ | Field absent — must be inferred or enriched |
| 🔴 | Field absent AND difficult to infer |

---

## Dataset Profiles

### 1. RecipeNLG
**URL:** https://recipenlg.cs.put.poznan.pl/  
**Hugging Face:** https://huggingface.co/datasets/mbien/recipe_nlg  
**License:** Custom non-commercial — research and educational use only. Commercial use requires contacting Poznań University of Technology. **Cannot be used directly in a commercial app without permission.**  
**Size:** 2,231,142 recipes  
**Format:** CSV / HuggingFace dataset  
**Language:** English only

#### Fields Available

| Required Field | Status | Notes |
|---|---|---|
| title | ✅ | Present for all records |
| description | ❌ | Not included |
| ingredients (structured name/amount/unit) | 🟡 | Raw strings like "1 c. firmly packed brown sugar" — amount+unit+name are combined in one string, NOT split into sub-fields. NER entities (`ner` column) give just canonical ingredient names. |
| steps/instructions | ✅ | List of step strings; no section structure |
| time_prep_min | ❌ | Absent |
| time_cook_min | ❌ | Absent |
| time_total_min | ❌ | Absent |
| serves | ❌ | Absent |
| difficulty | ❌ | Absent |
| cuisine_tags | ❌ | Absent natively; community extensions (3A2M) add 9 broad genres (bakery, drinks, non-veg, vegetables, fast food, cereals, meals, sides, fusion) but not geographic cuisine |
| flavor_tags | ❌ | Absent |
| texture_tags | ❌ | Absent |
| dietary_tags / dietary_flags | ❌ | Absent; must be inferred from ingredient NER entities |
| nutrition_per_serving | ❌ | Absent |
| season_tags | ❌ | Absent |
| occasion_tags | ❌ | Absent |
| course_tags | ❌ | Absent |

**Schema (exact columns):**
```
id, title, ingredients (list<str>), directions (list<str>), link, source, ner (list<str>)
```

#### Data Quality
- High volume; well-deduplicated (523K near-duplicates removed)
- English-only, heavily US/Western-biased (sourced from cookbooks.com, allrecipes, etc.)
- Ingredients are unstructured strings — quantity/unit parsing requires a downstream NLP pipeline (e.g. NYT ingredient parser)
- No cuisine classification, times, servings, or dietary flags
- NER entities are clean ingredient names useful for dietary inference via ingredient lookup tables

#### Gap Analysis
| Missing Field | Inference Strategy |
|---|---|
| Structured ingredients | Apply NYT ingredient parser or spaCy NER to split amount/unit/name |
| times | Cannot infer reliably; LLM estimation possible but noisy |
| serves | Cannot infer reliably |
| cuisine_tags | Train classifier on title + NER entities (RecipeDB provides labeled training data for 26 regions) |
| dietary flags | Map NER ingredient list against curated allergen/dietary lookup tables (e.g. pork terms → contains_pork) |
| nutrition | USDA FoodData Central lookup on NER ingredients after unit normalization |
| flavor/texture/occasion | LLM annotation pass or embedding similarity against seed tagged recipes |

---

### 2. Recipe1M+
**URL:** https://im2recipe.csail.mit.edu/  
**License:** Research and non-commercial use only — must create an account and agree to terms. **Not free for commercial app use.** Commercial licensing requires contacting MIT CSAIL directly.  
**Size:** ~1,029,720 recipes + 13M food images (Recipe1M+)  
**Format:** JSON layers (layer1.json, layer2.json)  
**Language:** English

#### Fields Available

| Required Field | Status | Notes |
|---|---|---|
| title | ✅ | Present |
| description | ❌ | Absent |
| ingredients (structured) | 🟡 | `unit` and `quantity` fields extracted where possible; empty when not parseable. NER detections in `det_ingrs.json` provide canonical names. |
| steps/instructions | ✅ | Ordered list; note: Recipe1M (original) had sentences split as steps rather than real step boundaries — RecipeNLG corrected this |
| time_prep_min | ❌ | Absent |
| time_cook_min | ❌ | Absent |
| time_total_min | ❌ | Absent |
| serves | ❌ | Absent |
| difficulty | ❌ | Absent |
| cuisine_tags | ❌ | No direct cuisine label; FoodKG links recipe IDs to some category info |
| dietary_tags / dietary_flags | ❌ | Absent; ingredient-based inference only |
| nutrition_per_serving | 🟡 | Energy, protein, sugar, fat, saturates, salt — computed by Recipe1M+ authors via USDA matching. Coverage incomplete (~70-80% of recipes). |
| flavor/texture/occasion | ❌ | Absent |

**Schema (layer1.json):**
```json
{
  "id": "...",
  "title": "...",
  "ingredients": [{"text": "...", "qty": "...", "unit": "..."}],
  "instructions": [{"text": "..."}],
  "partition": "train/val/test",
  "url": "..."
}
```

#### Data Quality
- Better structured than RecipeNLG at ingredient level (qty/unit extracted)
- Access restricted (account + ToS agreement) — friction for automated pipelines
- Non-commercial restriction makes it **unsuitable as a primary corpus for a product app** without explicit licensing

#### Gap Analysis
Same as RecipeNLG. The nutrition data from the authors (USDA-matched) is the main advantage over RecipeNLG, but it is partial.

---

### 3. TheMealDB
**URL:** https://www.themealdb.com/api.php  
**License:** Free API for development/educational use (test key "1"). **Commercial apps require Patreon supporter tier (~$10 lifetime one-off).** Database licensed for commercial use with attribution.  
**Size:** ~598 recipes (as of April 2026, up from ~283 cited in older sources)  
**Format:** REST JSON API  
**Access:** No bulk download on free tier; full DB listing requires premium key

#### Fields Available (exact API response fields)

| Required Field | Status | Notes |
|---|---|---|
| title | ✅ | `strMeal` |
| description | ❌ | Absent |
| ingredients (structured) | 🟡 | Up to 20 ingredient slots (`strIngredient1`–`strIngredient20`) with corresponding measures (`strMeasure1`–`strMeasure20`). Names and measures are plain text strings — not split into amount/unit sub-fields. Max 20 ingredients per recipe. |
| steps/instructions | ✅ | `strInstructions` — single text block, not split into steps |
| time_prep_min | ❌ | Absent |
| time_cook_min | ❌ | Absent |
| time_total_min | ❌ | Absent |
| serves | ❌ | Absent |
| difficulty | ❌ | Absent |
| cuisine_tags | ✅ | `strArea` (e.g. "Japanese", "Indian", "Mexican", "Canadian"); excellent geographic coverage across ~29 areas |
| course/category | ✅ | `strCategory` (e.g. "Chicken", "Seafood", "Dessert", "Side"); 14+ categories |
| flavor_tags | ❌ | Absent |
| texture_tags | ❌ | Absent |
| dietary_tags / dietary_flags | ❌ | Absent; only ingredient-based inference possible |
| nutrition_per_serving | ❌ | Absent |
| season_tags | ❌ | Absent |
| occasion_tags | ❌ | `strTags` field sometimes present (e.g. "Meat,Casserole") but sparse |
| images | ✅ | `strMealThumb` + multiple sizes |
| youtube | ✅ | `strYoutube` |

**Other API fields:** `idMeal`, `strSource`, `strImageSource`, `strCreativeCommonsConfirmed`, `dateModified`

#### Data Quality
- Small corpus (~598 meals) — insufficient as a standalone recipe dataset for a recommendation engine
- Excellent cuisine area tagging — best free source for geographic cuisine labels at small scale
- Instructions are a single unbroken text block
- Ingredient parsing needed (measures like "3/4 cup" are raw strings)
- Crowd-sourced quality — some inconsistencies in formatting

#### Gap Analysis
Primarily useful as a **high-quality labeled seed dataset** (cuisine/category labels) to train or calibrate cuisine classifiers on larger corpora. Not suitable as a primary corpus.

---

### 4. Open Food Facts
**URL:** https://world.openfoodfacts.org/data  
**License:** Database: Open Database License (ODbL) — free for any use including commercial, with attribution and share-alike. Individual contents: Database Contents License. Images: CC BY-SA.  
**Size:** ~3M food **products** (not recipes)  
**Format:** CSV/JSONL bulk download, REST API, HuggingFace dataset  
**Hugging Face:** https://huggingface.co/datasets/openfoodfacts/product-database

#### Nature of the Data
Open Food Facts is a **packaged food products database**, not a recipe database. Each record is a scanned grocery product (barcode), not a dish. It is relevant for a recipe RAG pipeline only as a **nutrition enrichment reference** to look up specific packaged ingredients by name or barcode.

#### Fields Available

| Field | Status | Notes |
|---|---|---|
| product_name | ✅ | Product name as on packaging |
| ingredients_text | ✅ | Raw ingredients list from label |
| ingredients_tags | 🟡 | Parsed ingredient list (taxonomy in progress) |
| allergens_tags | ✅ | Standardized allergen list (e.g. en:nuts, en:gluten) |
| nutriments | ✅ | energy-kcal, proteins_100g, fat_100g, carbohydrates_100g, fiber_100g, sugars_100g, salt_100g, etc. per 100g and per serving |
| nutriscore_grade | ✅ | A–E Nutri-Score |
| nova_group | ✅ | 1–4 NOVA ultra-processing score |
| vegan/vegetarian tags | 🟡 | Computed from ingredient analysis; not 100% reliable |
| categories_tags | ✅ | Product category taxonomy |
| countries_tags | ✅ | Where sold |
| serving_size | 🟡 | Available but inconsistent format |

#### Cross-Reference Use for Recipes
**Strategy:** After parsing recipe ingredients to canonical ingredient names (via NER on RecipeNLG/Recipe1M+ data), match ingredient names against Open Food Facts product_name or ingredients_tags to retrieve nutrition data. This works best for packaged ingredients (e.g. "canned tomatoes") but less well for raw produce.  
**Better approach for raw ingredients:** Use USDA FoodData Central (see below), which has better coverage of raw/unprocessed foods.

#### Data Quality
- 3M+ products, very good for branded/packaged items
- Coverage highly skewed toward French and European products (contributor base)
- Raw produce coverage sparse compared to USDA
- Ingredient text and nutrition completeness varies widely (crowd-sourced)
- Useful supplement, not a primary recipe source

---

### 5. USDA FoodData Central
**URL:** https://fdc.nal.usda.gov/  
**API Guide:** https://fdc.nal.usda.gov/api-guide  
**License:** CC0 1.0 Universal — **fully public domain, no restrictions, commercial use permitted**  
**Size:** 300,000+ food items across 5 databases:
- Foundation Foods: ~1,200 raw/minimally processed foods with detailed nutrient data
- SR Legacy: ~7,800 standard reference foods
- Branded Foods: ~500K branded products
- FNDDS Survey Foods: ~7,000 foods as eaten
- Experimental Foods: research data

#### Nutrients Available per Food Item
- Energy (kcal, kJ)
- Protein (g)
- Total fat (g), saturated fat, trans fat, monounsaturated, polyunsaturated
- Carbohydrates (g), dietary fiber (g), total sugars (g)
- Sodium/salt (mg)
- Cholesterol, vitamins (A, C, D, E, K, B1–B12, folate), minerals (Ca, Fe, Mg, K, Zn, P)
- Serving size and yield information

#### Use in Recipe Pipeline

| Use Case | Approach |
|---|---|
| Nutrition per serving | Match recipe ingredient names to FDC food descriptions via string similarity (Modified Jaccard / BM25); multiply by quantity; sum across ingredients; divide by servings |
| is_vegan / is_vegetarian | Map ingredient → FDC category; apply rules (no meat/dairy/eggs = vegan, etc.) |
| Allergen detection (nuts, shellfish, gluten, dairy) | Map ingredient names against allergen category taxonomy |

**RecipeDB's authors report 94.49% ingredient match rate** using Modified Jaccard Index against USDA SR (slightly older version of FDC). For a RAG pipeline, this is a strong baseline.

**API Access:** Free with a data.gov API key (sign-up required). Bulk downloads available for all databases.

#### Data Quality
- Authoritative, lab-tested nutritional values (Foundation Foods)
- Coverage gap: non-American/ethnic ingredients (e.g. "garam masala", "miso paste", "dashi") often absent
- Handling required for recipe measurement units → grams conversion before nutrient calculation

---

### 6. Epicurious / Kaggle Dataset
**URL:** https://www.kaggle.com/datasets/hugodarwood/epirecipes  
**License:** CC BY-SA 3.0 — **free for commercial use with attribution**  
**Size:** ~20,052 recipes  
**Format:** CSV  
**Source:** Scraped from Epicurious.com

#### Fields Available

| Required Field | Status | Notes |
|---|---|---|
| title | ✅ | Recipe name |
| description | ❌ | Not in this Kaggle version |
| ingredients (structured) | 🟡 | Ingredient binary presence matrix (one column per ~680 unique ingredients, 0/1). Not quantities or amounts — just presence/absence. |
| steps/instructions | ❌ | Not in this Kaggle version; raw HTML version has them |
| time_prep_min | ❌ | Absent |
| time_cook_min | ❌ | Absent |
| time_total_min | ❌ | Absent |
| serves | ❌ | Absent |
| difficulty | ❌ | Absent |
| cuisine_tags | 🟡 | Some category columns present (e.g. "backyard barbecue", "summer", "fall") as binary flags |
| course_tags | 🟡 | Meal type columns: "breakfast", "lunch", "dinner", "appetizer", "dessert" as binary flags |
| season_tags | 🟡 | "winter", "spring", "summer", "fall" as binary flags |
| occasion_tags | 🟡 | "holiday", "thanksgiving", "christmas" style flags present |
| nutrition | 🟡 | calories, protein (g), fat (g), sodium (mg) — 4 basic macros; ~4K recipes have null calories |
| rating | ✅ | 0–5 scale user rating |
| dietary_flags | 🟡 | "vegetarian", "vegan", "low-fat", "low-sodium" style flags present |

**Note on the 13k Epicurious variant (CC BY-SA 3.0):** https://github.com/josephrmartinez/recipe-dataset — Contains only title, ingredient strings, and instructions (3 columns). More useful for text content but lacks metadata.

#### Data Quality
- Moderate size; well-curated editorial content from Epicurious
- The main Kaggle version has a wide column schema of binary flags rather than free-text tags — useful for supervised ML training labels
- Very limited nutrition data (4 macros, many nulls)
- No step-by-step instruction structure in the binary-matrix version
- American/Western cuisine heavily dominant

#### Gap Analysis
The binary flag columns for categories, seasons, occasions, and dietary info are actually useful training labels for a classifier. However, ingredient amounts and steps are missing. Best used as a **labeled training set** for classification tasks rather than as a primary recipe corpus.

---

### 7. Food.com (GeniusKitchen) — Kaggle
**URL:** https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions  
**Also:** https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews (500K variant)  
**License:** Unknown/unspecified on Kaggle; source data belongs to Food.com. **Commercial use legally ambiguous — treat as non-commercial research only without a direct license from Food.com.**  
**Size:** 
- shuyangli94 version: ~83,782 recipes (RAW_recipes.csv) + 731,927 interactions
- irkaal version: ~500K recipes + 1.4M reviews  
**Format:** CSV

#### Fields Available (RAW_recipes.csv — shuyangli94 version)

| Required Field | Status | Notes |
|---|---|---|
| title (name) | ✅ | Recipe name |
| description | ✅ | User-provided description text |
| ingredients | 🟡 | List of ingredient strings (raw text, unstructured amounts) |
| steps (instructions) | ✅ | Ordered list of step strings |
| time_total_min (minutes) | ✅ | Total time in minutes |
| time_prep_min | ❌ | Not separate from total |
| time_cook_min | ❌ | Not separate from total |
| serves (n_servings) | 🟡 | Some versions include serving count |
| nutrition | ✅ | calories, fat, sugar, sodium, protein, saturated_fat, carbs — per serving as a list |
| n_steps | ✅ | Step count |
| n_ingredients | ✅ | Ingredient count |
| tags | ✅ | Rich user-assigned tag list (e.g. "60-minutes-or-less", "vegetarian", "low-sodium", "european", "italian", "meat") — very diverse |
| submitted_date | ✅ | |
| contributor_id | ✅ | |
| difficulty | ❌ | Absent |
| cuisine_tags | 🟡 | Present via tags (e.g. "italian", "japanese") but not a clean structured field |
| flavor_tags | 🟡 | Some tags (e.g. "spicy", "savory") present in tag list but uncontrolled vocabulary |
| dietary_flags | 🟡 | Tags include "vegetarian", "vegan", "gluten-free" but coverage inconsistent |

**irkaal 500K version** adds: `RecipeId`, `Name`, `CookTime`, `PrepTime`, `TotalTime`, `RecipeIngredientQuantities`, `RecipeIngredientParts`, `Calories`, `FatContent`, `SaturatedFatContent`, `CholesterolContent`, `SodiumContent`, `CarbohydrateContent`, `FiberContent`, `SugarContent`, `ProteinContent`, `RecipeServings`, `RecipeYield`, `RecipeCategory`, `RecipeInstructions`, `Keywords`

#### Data Quality
- Very large corpus with rich user-generated tags — excellent for tag-based recommendation
- The 500K irkaal version has separated prep/cook/total time and structured nutrition macros
- License ambiguity is the main concern for commercial use
- Ingredient amounts are unstructured strings, not structured sub-fields
- Tags are user-assigned — no controlled vocabulary, many noisy entries (e.g. "number-of-servings-4" as a tag)
- High US/Western bias

---

### 8. RecipeDB
**URL:** https://cosylab.iiitd.edu.in/recipedb/  
**Paper:** https://pmc.ncbi.nlm.nih.gov/articles/PMC7687679/  
**License:** Creative Commons Attribution-NonCommercial-ShareAlike 3.0 (CC BY-NC-SA 3.0) — **non-commercial only**  
**Size:** 118,171 recipes  
**Format:** Web interface + companion data on GitHub (https://github.com/cosylabiiit/Recipedb-companion-data); no bulk CSV download publicly confirmed  
**Sources:** AllRecipes.com + Food.com (GeniusKitchen)

#### Fields Available

| Required Field | Status | Notes |
|---|---|---|
| title | ✅ | |
| description | ❌ | Not documented |
| ingredients (structured) | ✅ | NER-extracted: name, state (ground/fresh), unit, quantity, size, temperature, dry/fresh — 7 attributes per ingredient |
| steps/instructions | ✅ | Temporal sequence (Early/Middle/Late stage) |
| time_prep_min | 🟡 | "Preparation time when available" — not universal |
| serves | ❌ | Not documented |
| difficulty | ❌ | Absent |
| cuisine_tags | ✅ | 26 geocultural regions, 74 countries, 6 continents — best global coverage of any free dataset |
| dietary_tags | ✅ | 5 dietary styles: Vegan, Pescetarian, Lacto-Vegetarian, Ovo-Vegetarian, Ovo-Lacto-Vegetarian |
| nutrition_per_serving | ✅ | Estimated via USDA NDB lookup: calories, carbs, protein, fat (macros + micronutrients where available) |
| ingredient_category | ✅ | 29 categories per ingredient (Meat, Fish, Dairy, Vegetable, Herb, Spice, etc.) |
| flavor links | ✅ | Links to FlavorDB (flavor molecule profiles) — not flavor tags per se |
| cooking processes | ✅ | 268 techniques tagged per recipe |
| utensils | ✅ | 69 utensil types |
| season_tags | ❌ | Absent |
| occasion_tags | ❌ | Absent |
| course_tags | ❌ | Absent |
| texture_tags | ❌ | Absent |
| difficulty | ❌ | Absent |

#### Data Quality
- Best structured ingredient data of any free dataset (7-attribute NER)
- Best global cuisine coverage (26 regions, 74 countries)
- USDA-linked nutrition estimates available
- Non-commercial license limits product use
- No bulk download readily available (companion data on GitHub has training sets, not full recipe dump)
- 118K recipes is modest scale

---

### 9. FoodKG (Knowledge Graph)
**URL:** https://foodkg.github.io/  
**License:** Not explicitly stated. Built on top of Recipe1M (non-commercial) + USDA (CC0) + FoodOn (CC BY).  
**Size:** ~1M recipes, 67M triples  
**Format:** RDF triples, requires Blazegraph or similar triple store

#### Fields Available (via SPARQL)
- Recipe title, ingredients, instructions (from Recipe1M base)
- Detected ingredient entities (NER)
- Nutritional data per ingredient (from USDA FoodData Central)
- Food ontology classification via FoodOn
- Linkages: recipe ↔ ingredient ↔ nutrition ↔ food ontology

#### Data Quality and Suitability
- Academically powerful for semantic querying (e.g. "find recipes without allergens X using ingredient substitutes")
- **Heavy infrastructure requirement** — not practical as a flat file dataset for a RAG pipeline without significant engineering
- Inherits Recipe1M's non-commercial license problem
- Construction scripts available but require the Recipe1M dataset (requires account)
- Better suited as an **enrichment ontology reference** than as a recipe corpus

---

### 10. datahiveai/recipes-with-nutrition (Hugging Face)
**URL:** https://huggingface.co/datasets/datahiveai/recipes-with-nutrition  
**License:** CC BY-NC 4.0 — **non-commercial only**  
**Size:** 39,447 recipes  
**Format:** CSV (450 MB) on HuggingFace  
**Sources:** Serious Eats, Food52, taste.com.au, etc.

#### Fields Available

| Required Field | Status | Notes |
|---|---|---|
| recipe_name | ✅ | |
| source / url | ✅ | |
| servings | ✅ | Float |
| calories | ✅ | Total (not per-serving) |
| total_weight_g | ✅ | |
| image_url | ✅ | |
| diet_labels | ✅ | e.g. "High-Fiber", "Low-Carb", "High-Protein" |
| health_labels | ✅ | e.g. "Vegan", "Vegetarian", "Dairy-Free", "Gluten-Free", "Egg-Free", "Tree-Nut-Free", "Fish-Free", "Shellfish-Free", "Pork-Free", etc. — ~14 labels |
| cautions | ✅ | e.g. "Gluten", "Wheat", "Sulfites" |
| cuisine_type | ✅ | e.g. "asian", "french", "italian" — lowercase, ~20 values |
| meal_type | ✅ | "lunch/dinner", "breakfast", "snack" |
| dish_type | ✅ | "main course", "salad", "starter", etc. |
| ingredient_lines | ✅ | Raw ingredient strings (list) |
| ingredients | ✅ | Structured: {food, text, weight (g), measure, quantity} per ingredient — parsed via EDAMAM API |
| total_nutrients | ✅ | Full USDA-style panel: energy, fat, saturated fat, trans fat, mono/polyunsaturated, carbs, net carbs, fiber, sugars, protein, cholesterol, sodium, Ca, Mg, K, Fe, Zn, P, vitamins A/C/D/E/K/B1/B2/B3/B6/B12/folate, water |
| daily_values (%) | ✅ | %DV for all nutrients |
| time_prep_min | ❌ | Absent |
| time_cook_min | ❌ | Absent |
| serves (structured) | ✅ | `servings` field |
| difficulty | ❌ | Absent |
| texture_tags | ❌ | Absent |
| season_tags | ❌ | Absent |

**Key strength:** This dataset has the most complete **structured ingredient data** (weight in grams, measure, quantity) and the most complete **health/dietary labeling** of any free dataset, combined with full nutrient panels. The CC BY-NC license limits commercial use.

---

### 11. EDAMAM (Reference — Not Open Data)
**URL:** https://www.edamam.com/  
**License:** Commercial SaaS API — not free for production use  
**Note:** The datahiveai dataset above was created using EDAMAM's Recipe and Nutrition Analysis API. The EDAMAM API itself provides exactly the fields needed (cuisine, meal type, health labels, full nutrition, structured ingredients) but costs money. The datahiveai dataset is a derivative CC BY-NC export of EDAMAM's output.

---

### 12. CulinaryDB
**URL:** https://cosylab.iiitd.edu.in/culinarydb/  
**License:** Not explicitly stated on website  
**Size:** Not stated on website; covers 22+ world regions  
**GitHub companion:** https://github.com/cosylabiiit/Recipedb-companion-data  
**Note:** CulinaryDB is the precursor to RecipeDB, focusing on ingredient-region analysis. It is subsumed by RecipeDB for most practical purposes.

---

### 13. Wikibooks Cookbook
**URL:** https://en.wikibooks.org/wiki/Cookbook:Recipes  
**License:** CC BY-SA 3.0 — free for commercial use with attribution  
**Size:** ~500–1000 recipes (accessible via API; full count uncertain)  
**Format:** Wikitext; requires MediaWiki API parsing  
**API endpoint:** `https://en.wikibooks.org/w/api.php?action=query&generator=categorymembers&gcmtitle=Category:Recipes&gcmlimit=max&format=json`

#### Fields Available
- Recipe title
- Cuisine, Recipe origin, Yield, Servings, Time, Difficulty (structured template when populated)
- Ingredients (wiki table format — requires parsing)
- Instructions (wiki text)
- Categories

#### Data Quality
- Small, inconsistently structured (wiki markup requires custom parser)
- Some recipes have good structured metadata (from the `{{Recipe summary}}` template)
- Not practical as a primary corpus at this scale
- Best suited as a supplemental source for specific edge-case cuisines

---

## Consolidated Comparison Table

| Dataset | License | App Use? | Size | title | description | ingredients (structured) | instructions (steps) | prep/cook/total time | serves | difficulty | cuisine_tags | dietary_flags | nutrition | flavor/texture | course/occasion | Cuisine Diversity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **RecipeNLG** | Non-commercial (PUT) | ❌ No | 2.2M | ✅ | ❌ | 🟡 raw strings + NER names | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ infer | ❌ | ❌ | ❌ | Low (US/Western) |
| **Recipe1M+** | Non-commercial (MIT) | ❌ No | 1M | ✅ | ❌ | 🟡 qty+unit attempted | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ infer | 🟡 partial | ❌ | ❌ | Low (US/Western) |
| **TheMealDB** | Free dev; paid commercial | 🟡 Paid | ~598 | ✅ | ❌ | 🟡 name+measure strings | 🟡 single block | ❌ | ❌ | ❌ | ✅ 29 areas | ❌ | ❌ | ❌ | 🟡 tags | High (global) |
| **Open Food Facts** | ODbL (free incl. commercial) | ✅ Yes | 3M products | n/a | n/a | ✅ (product ingredients) | n/a | n/a | 🟡 | n/a | n/a | ✅ allergens | ✅ full | n/a | n/a | High (global) |
| **USDA FoodData Central** | CC0 (public domain) | ✅ Yes | 300K+ foods | n/a | n/a | n/a (food items) | n/a | n/a | 🟡 serving | n/a | n/a | 🟡 category | ✅ authoritative | n/a | n/a | Medium (US-centric) |
| **Epicurious / Kaggle** | CC BY-SA 3.0 | ✅ Yes | ~20K | ✅ | ❌ | ❌ binary flags only | ❌ | ❌ | ❌ | ❌ | 🟡 flags | 🟡 flags | 🟡 4 macros | ❌ | ✅ season/occasion flags | Low (US/Western) |
| **Food.com (irkaal 500K)** | Unspecified | ⚠️ Risky | 500K | ✅ | 🟡 | 🟡 qty+parts separated | ✅ | ✅ all 3 | ✅ | ❌ | 🟡 keywords | 🟡 keywords | ✅ 7 macros | ❌ | ✅ keywords | Low (US/Western) |
| **Food.com (shuyangli94)** | Unspecified | ⚠️ Risky | 83K | ✅ | ✅ | 🟡 strings | ✅ | ✅ total only | 🟡 | ❌ | 🟡 tags | 🟡 tags | ✅ 7 macros | ❌ | 🟡 tags | Low (US/Western) |
| **RecipeDB** | CC BY-NC-SA 3.0 | ❌ No | 118K | ✅ | ❌ | ✅ 7-attr NER | ✅ | 🟡 partial | ❌ | ❌ | ✅ 26 regions | ✅ 5 types | ✅ estimated | ❌ | ❌ | High (74 countries) |
| **datahiveai/nutrition** | CC BY-NC 4.0 | ❌ No | 39K | ✅ | ❌ | ✅ weight+measure+qty | ✅ via URL | ❌ | ✅ | ❌ | ✅ ~20 types | ✅ 14 labels | ✅ full panel | ❌ | ✅ meal/dish type | Medium |
| **FoodKG** | Unclear (Recipe1M base) | ❌ No | ~1M | ✅ | ❌ | ✅ NER linked | ✅ | ❌ | ❌ | ❌ | 🟡 | 🟡 infer | ✅ USDA-linked | ❌ | ❌ | Low |
| **Wikibooks Cookbook** | CC BY-SA 3.0 | ✅ Yes | ~500–1K | ✅ | ❌ | 🟡 needs parsing | ✅ | 🟡 template | 🟡 template | 🟡 template | 🟡 | ❌ | ❌ | ❌ | ❌ | Medium |

---

## Field-by-Field Gap Analysis

### Fields Available in At Least One Free Dataset

| Field | Best Free Source | Commercial-Safe Source |
|---|---|---|
| title | All datasets | Epicurious (CC BY-SA 3.0), Food.com (risky), Wikibooks |
| description | Food.com shuyangli94 | Food.com (risky) |
| ingredients (raw strings) | RecipeNLG, Food.com | Epicurious (binary only), Food.com (risky) |
| ingredients (structured: name+qty+unit) | datahiveai, RecipeDB, Recipe1M+ | None commercial-safe; must parse via NER |
| steps / instructions | RecipeNLG, Food.com, RecipeDB | Food.com (risky), Epicurious (13k variant) |
| time_prep_min | Food.com irkaal | Food.com (risky) |
| time_cook_min | Food.com irkaal | Food.com (risky) |
| time_total_min | Food.com, RecipeNLG (absent) | Food.com (risky) |
| serves | Food.com irkaal, datahiveai | Food.com (risky) |
| difficulty | TheMealDB template (absent), Wikibooks template | Wikibooks (very sparse) |
| cuisine_tags (geographic) | TheMealDB (29 areas), RecipeDB (26 regions/74 countries), datahiveai | Must classify; seed labels from TheMealDB/RecipeDB |
| dietary_flags (is_vegan, etc.) | datahiveai (14 labels), RecipeDB (5 types) | Infer from ingredient lists |
| dietary_flags (is_halal_ok, contains_pork, etc.) | None natively | Must infer from ingredient lookup tables |
| nutrition (kcal, protein, fat, carbs, fiber, sugar, salt) | USDA FDC (CC0) as lookup; datahiveai has computed values; Food.com has 7 macros | USDA FDC (CC0) for ingredient-level lookup |
| flavor_tags | None | Must generate via LLM or rule-based approach |
| texture_tags | None | Must generate via LLM or rule-based approach |
| season_tags | Epicurious binary flags | Epicurious (CC BY-SA 3.0) — limited |
| occasion_tags | Epicurious binary flags, Food.com tags | Epicurious, Food.com (risky) |
| course_tags | Food.com (RecipeCategory), datahiveai (dish_type), TheMealDB (category) | Infer from title/tags |

### Fields That Must Be Generated

| Field | Recommended Approach |
|---|---|
| difficulty | Train regressor on: n_steps, n_ingredients, avg_instruction_length, presence of specific techniques (e.g. "temper", "julienne", "bain-marie"). Seed labels from Wikibooks difficulty template or manual annotation of ~500 recipes. |
| flavor_tags (umami, spicy, sweet, bitter, sour) | (1) Rule-based: map ingredients to flavor profiles via flavor molecule databases (FlavorDB links in RecipeDB); (2) LLM batch annotation on title + ingredients; (3) Fine-tune classifier on seed-labeled examples |
| texture_tags (crispy, creamy, crunchy, etc.) | LLM annotation on recipe title + steps (look for oil/frying → crispy; cream/butter → creamy; etc.) |
| cuisine_tags (for non-TheMealDB sources) | (1) Train classifier on RecipeDB's 74-country labels; (2) Use TheMealDB's area labels as seed; (3) LLM zero-shot classification |
| is_halal_ok | Ingredient lookup: flag as false if contains pork products, alcohol, or non-halal-certified meat terms |
| contains_pork | Ingredient lookup against pork ingredient list (bacon, ham, lard, prosciutto, chorizo, etc.) |
| contains_shellfish | Ingredient lookup against shellfish ingredient list |
| contains_alcohol | Ingredient lookup: beer, wine, spirits, liqueur, etc. |
| season_tags | Rule-based from seasonal ingredient lists + occasion tags; LLM for ambiguous cases |

---

## Recommended Dataset Strategy for RAG Pipeline

### Option A: Non-Commercial Research / Internal Use Only

**Primary corpus:** RecipeNLG (2.2M) + RecipeDB (118K)  
**Nutrition enrichment:** USDA FoodData Central (CC0)  
**Cuisine labels:** RecipeDB (26 regions), TheMealDB (training seed)  
**Dietary labels:** datahiveai/recipes-with-nutrition as training labels; RecipeDB as reference  
**Structured ingredients:** Apply NER pipeline (trained on RecipeDB's 7-attribute training data from GitHub) to RecipeNLG ingredient strings  
**Gaps to fill:** Times (LLM estimation or NLP from instructions), difficulty (regression model), flavor/texture (LLM annotation), halal/pork/alcohol flags (ingredient lookup)

### Option B: Commercial App Use

**Primary corpus:** Food.com irkaal 500K — license is technically unspecified but high-risk. Alternatives:
- Epicurious 13K variant (CC BY-SA 3.0) — small but commercially clean
- Wikibooks Cookbook (~1K, CC BY-SA 3.0) — tiny
- Consider licensing TheMealDB (one-off payment) for the full DB (~598 meals)

**True commercial path:** The safest route is to **generate/curate your own dataset** using:
1. USDA FoodData Central (CC0) for ingredient and nutrition data
2. TheMealDB commercial tier for 600 high-quality seeded examples
3. LLM-generated recipes with LLM-generated fields, using above datasets as reference
4. Open user-contributed content (build your own community corpus)

**Critical note on RecipeNLG for commercial apps:** The PUT license explicitly states non-commercial, research/educational use only. Using it in a production food app likely violates the license.

---

## Summary Scorecard

| Dataset | Commercial OK | Scale | Structured Ingredients | Cuisine Coverage | Times | Nutrition | Dietary Flags |
|---|---|---|---|---|---|---|---|
| RecipeNLG | ❌ | ⭐⭐⭐⭐⭐ (2.2M) | ⭐ (raw strings) | ⭐ (US bias) | ❌ | ❌ | ❌ |
| Recipe1M+ | ❌ | ⭐⭐⭐⭐⭐ (1M) | ⭐⭐ (partial) | ⭐ (US bias) | ❌ | ⭐⭐ (partial) | ❌ |
| TheMealDB | ⭐⭐⭐ (paid) | ⭐ (598) | ⭐ (name+measure) | ⭐⭐⭐⭐⭐ (global) | ❌ | ❌ | ❌ |
| Open Food Facts | ✅ | ⭐⭐⭐⭐⭐ (3M products) | ⭐⭐⭐ (packaged only) | ⭐⭐⭐ (global) | n/a | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| USDA FoodData Central | ✅ | ⭐⭐⭐⭐ (300K foods) | ⭐⭐⭐⭐⭐ (lab data) | ⭐⭐ (US-centric) | n/a | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| Epicurious/Kaggle | ✅ | ⭐⭐ (20K) | ⭐ (binary only) | ⭐⭐ (US bias) | ❌ | ⭐ (4 macros) | ⭐⭐ |
| Food.com (500K) | ⚠️ unclear | ⭐⭐⭐⭐⭐ (500K) | ⭐⭐ (qty+parts) | ⭐⭐ (US bias) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ (7 macros) | ⭐⭐ |
| RecipeDB | ❌ | ⭐⭐⭐ (118K) | ⭐⭐⭐⭐⭐ (7-attr NER) | ⭐⭐⭐⭐⭐ (74 countries) | ⭐ (partial) | ⭐⭐⭐ (estimated) | ⭐⭐⭐ |
| datahiveai/nutrition | ❌ | ⭐⭐ (39K) | ⭐⭐⭐⭐⭐ (weight+qty+measure) | ⭐⭐⭐ (20 cuisine types) | ❌ | ⭐⭐⭐⭐⭐ (full panel) | ⭐⭐⭐⭐⭐ |
| FoodKG | ❌ | ⭐⭐⭐⭐⭐ (1M) | ⭐⭐⭐⭐ (NER + ontology) | ⭐⭐ | ❌ | ⭐⭐⭐⭐ (USDA linked) | ⭐⭐ |
| Wikibooks | ✅ | ⭐ (~1K) | ⭐⭐ (parseable) | ⭐⭐⭐ | ⭐⭐ (template) | ❌ | ❌ |

---

## Sources

- RecipeNLG paper (Bień et al., 2020): https://aclanthology.org/2020.inlg-1.4/
- RecipeNLG HuggingFace card: https://huggingface.co/datasets/mbien/recipe_nlg
- RecipeNLG download/license: https://recipenlg.cs.put.poznan.pl/dataset
- Recipe1M+ paper: https://im2recipe.csail.mit.edu/tpami19.pdf
- Recipe1M+ dataset: http://im2recipe.csail.mit.edu/
- TheMealDB API: https://www.themealdb.com/api.php
- TheMealDB FAQ (commercial use): https://www.themealdb.com/faq.php
- Open Food Facts data page: https://world.openfoodfacts.org/data
- Open Food Facts API: https://openfoodfacts.github.io/openfoodfacts-server/api/
- Open Food Facts HuggingFace: https://huggingface.co/datasets/openfoodfacts/product-database
- USDA FoodData Central: https://fdc.nal.usda.gov/
- USDA FoodData Central API Guide: https://fdc.nal.usda.gov/api-guide
- Epicurious Kaggle dataset: https://www.kaggle.com/datasets/hugodarwood/epirecipes
- Epicurious 13k variant: https://github.com/josephrmartinez/recipe-dataset
- Food.com 83K interactions: https://www.kaggle.com/datasets/shuyangli94/food-com-recipes-and-user-interactions
- Food.com 500K reviews: https://www.kaggle.com/datasets/irkaal/foodcom-recipes-and-reviews
- Food.com 500K with tags: https://www.kaggle.com/datasets/shuyangli94/foodcom-recipes-with-search-terms-and-tags
- RecipeDB paper (PMC): https://pmc.ncbi.nlm.nih.gov/articles/PMC7687679/
- RecipeDB companion data (GitHub): https://github.com/cosylabiiit/Recipedb-companion-data
- RecipeDB website: https://cosylab.iiitd.edu.in/recipedb/
- CulinaryDB website: https://cosylab.iiitd.edu.in/culinarydb/
- FoodKG knowledge graph: https://foodkg.github.io/
- FoodKG paper (RPI): http://www.cs.rpi.edu/~zaki/PaperDir/ISWC19.pdf
- datahiveai/recipes-with-nutrition: https://huggingface.co/datasets/datahiveai/recipes-with-nutrition
- Wikibooks Cookbook: https://en.wikibooks.org/wiki/Cookbook:Recipes
- 3A2M annotated dataset paper: https://arxiv.org/html/2303.16778
- Nutritional Profile Estimation paper (RecipeDB): https://arxiv.org/pdf/2004.12286
