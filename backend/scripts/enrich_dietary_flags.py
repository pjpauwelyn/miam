"""enrich_dietary_flags.py — Deterministic dietary-flag classifier for recipes_open.

Usage:
    python enrich_dietary_flags.py [--batch-size N] [--limit N] [--dry-run]

What it does:
    - Reads records that do NOT yet have dietary_flags written
      (skips 'dietary_tagged', 'deterministic_enriched', 'llm_enriched',
       'validated').
    - Scans data->'ingredients' (parsed array) and data->'raw_ingredients_text'
      (NER field) for presence/absence of ingredient category keywords.
    - Computes 7 boolean flags (all default False, conservative approach):
        is_vegetarian, is_vegan, is_gluten_free, is_dairy_free,
        is_nut_free, contains_shellfish, contains_nuts
    - Writes ONLY data->'dietary_flags'.
    - After writing dietary_flags:
        - If enrichment_status = 'course_tagged' => sets 'deterministic_enriched'
        - Otherwise => sets 'dietary_tagged'
    - Does NOT write tier, enrichment_flags, or provenance.
    - Fully idempotent / restartable.
    - Logs progress every 10,000 rows.

Ownership:
    CAT-B field: data->dietary_flags
    enrichment_status set to 'dietary_tagged' or 'deterministic_enriched'
    CAT-E columns (tier, enrichment_flags, provenance) are NOT touched.

Blocker philosophy:
    Conservative: false negatives are safer than false positives.
    If unsure, do NOT set a positive flag.
    e.g. is_vegetarian = False if ANY meat keyword found,
         but defaults True only when we are confident no meat is present
         AND ingredients list is non-empty.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time

try:
    from supabase import create_client, Client
except ImportError:
    print("Install supabase-py: pip install supabase", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocklists  (conservative: include common forms/variants)
# ---------------------------------------------------------------------------

MEAT_KEYWORDS: frozenset[str] = frozenset([
    # Beef
    "beef", "steak", "ground beef", "minced beef", "brisket", "short rib",
    "ribeye", "sirloin", "chuck", "flank", "skirt steak", "tenderloin",
    "veal", "oxtail", "tripe",
    # Pork
    "pork", "bacon", "ham", "prosciutto", "pancetta", "salami", "pepperoni",
    "chorizo", "sausage", "hot dog", "bratwurst", "kielbasa", "lard",
    "pork belly", "pork chop", "pork loin", "pulled pork", "spare rib",
    "pork rib", "fatback",
    # Poultry
    "chicken", "turkey", "duck", "goose", "quail", "pheasant", "guinea fowl",
    "chicken breast", "chicken thigh", "chicken wing", "whole chicken",
    "ground turkey", "turkey breast", "rotisserie chicken",
    # Lamb / game
    "lamb", "mutton", "venison", "elk", "bison", "boar", "rabbit", "hare",
    "kangaroo", "goat meat",
    # Generic
    "meat", "mince", "ground meat", "deli meat", "cold cut",
    "bone broth",  # animal origin; blocks vegetarian
    "gelatin", "gelatine",  # animal-derived
    "rennet",  # some cheeses; animal-derived
    "lard", "tallow", "suet",
    "anchovies", "anchovy",  # often in sauces; blocks vegetarian
    "worcestershire",  # contains anchovies
    "fish sauce",  # blocks vegetarian
])

SEAFOOD_KEYWORDS: frozenset[str] = frozenset([
    "fish", "salmon", "tuna", "cod", "halibut", "tilapia", "trout",
    "bass", "snapper", "grouper", "mahi", "swordfish", "sardine",
    "mackerel", "herring", "anchovy", "anchovies", "catfish", "pike",
    "perch", "pollock", "haddock", "flounder", "sole", "turbot",
    "sea bream", "branzino", "sea bass",
    "shrimp", "prawn", "lobster", "crab", "crayfish", "langoustine",
    "clam", "mussel", "oyster", "scallop", "squid", "calamari",
    "octopus", "cuttlefish",
    "abalone", "geoduck",
    "fish sauce", "oyster sauce", "shrimp paste", "fish paste",
    "fish stock", "seafood",
])

SHELLFISH_KEYWORDS: frozenset[str] = frozenset([
    "shrimp", "prawn", "lobster", "crab", "crayfish", "langoustine",
    "clam", "mussel", "oyster", "scallop", "squid", "calamari",
    "octopus", "cuttlefish", "abalone",
    "shrimp paste", "fish sauce",  # may contain shellfish
    "shellfish",
])

DAIRY_KEYWORDS: frozenset[str] = frozenset([
    "milk", "whole milk", "skim milk", "2% milk", "buttermilk",
    "cream", "heavy cream", "whipping cream", "double cream",
    "sour cream", "creme fraiche", "cr\u00e8me fra\u00eeche",
    "butter", "ghee",  # ghee is clarified butter; blocks dairy-free
    "cheese", "cheddar", "mozzarella", "parmesan", "parmigiano",
    "gruyere", "swiss cheese", "brie", "camembert", "gouda", "goat cheese",
    "ricotta", "cottage cheese", "cream cheese", "mascarpone",
    "feta", "halloumi", "manchego", "colby", "provolone",
    "yogurt", "yoghurt", "greek yogurt",
    "whey", "casein", "lactose",
    "evaporated milk", "condensed milk", "powdered milk", "milk powder",
    "ice cream",  # contains dairy (unless labelled vegan ice cream)
    "half and half", "half-and-half",
])

EGG_KEYWORDS: frozenset[str] = frozenset([
    "egg", "eggs", "egg white", "egg yolk", "whole egg",
    "hard boiled egg", "soft boiled egg", "poached egg",
    "egg wash", "beaten egg",
    "meringue",  # egg-white based
    "mayonnaise", "mayo",  # egg-based
    "hollandaise",  # egg-based sauce
])

GLUTEN_KEYWORDS: frozenset[str] = frozenset([
    "flour", "all purpose flour", "all-purpose flour", "bread flour",
    "cake flour", "pastry flour", "self-raising flour", "self rising flour",
    "whole wheat flour", "whole grain flour", "spelt flour", "einkorn flour",
    "wheat", "whole wheat", "bulgur", "semolina", "durum", "farro",
    "spelt", "kamut", "einkorn", "emmer",
    "barley", "rye", "triticale",
    "bread", "breadcrumb", "panko", "crouton",
    "pasta", "noodle", "couscous",
    "cracker", "biscuit", "cookie", "cake",  # baked goods assume gluten
    "pita", "naan", "tortilla", "wrap",  # wheat-based unless noted
    "soy sauce",  # traditional soy sauce contains wheat
    "beer",  # barley-based unless gluten-free beer noted
    "malt", "malt vinegar",
    "seitan",  # pure gluten
    "udon", "ramen", "soba",  # wheat unless noted (soba sometimes pure buckwheat)
    "dumpling wrapper", "wonton wrapper", "gyoza wrapper",
    "puff pastry", "phyllo", "filo",
    "baking powder",  # some contain wheat starch; conservative
])

NUT_KEYWORDS: frozenset[str] = frozenset([
    "almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut",
    "macadamia", "brazil nut", "pine nut", "chestnut",
    "peanut", "peanut butter",  # technically legume but treated as nut allergen
    "mixed nut", "nut",  # generic
    "almond flour", "almond meal", "almond milk",
    "cashew cream", "cashew milk",
    "walnut oil", "hazelnut oil",
    "praline",  # nut-based
    "marzipan",  # almond-based
    "nougat",  # often contains nuts
    "nutella",  # hazelnut
    "tahini",  # sesame; NOT a tree nut but sometimes treated similarly
    # Note: tahini/sesame is a separate allergen; we include it conservatively
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(data: dict) -> str:
    """Concatenate all text from ingredients for keyword scanning.

    Combines:
    - Parsed ingredient names (data->ingredients[*].name)
    - Raw ingredients text (data->raw_ingredients_text, the NER field)
    - Title (as additional signal)
    """
    parts: list[str] = []

    # Parsed ingredients
    for ing in (data.get("ingredients") or []):
        if isinstance(ing, dict):
            parts.append(ing.get("name") or "")
            parts.append(ing.get("original") or "")  # original string if present
        elif isinstance(ing, str):
            parts.append(ing)

    # Raw NER text
    raw = data.get("raw_ingredients_text")
    if isinstance(raw, str):
        parts.append(raw)
    elif isinstance(raw, list):
        parts.extend(str(r) for r in raw)

    # Title as extra signal
    parts.append(data.get("title") or "")

    return " ".join(parts).lower()


def _contains_any(text: str, keywords: frozenset[str]) -> bool:
    """Return True if any keyword appears in text as a whole word/phrase."""
    for kw in keywords:
        # Use word-boundary match for single words, substring match for phrases
        if " " in kw:
            if kw in text:
                return True
        else:
            # Whole-word boundary (avoid 'egg' matching 'eggnog')
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, text):
                return True
    return False


def compute_dietary_flags(data: dict) -> dict[str, bool]:
    """Compute all 7 dietary flags for a single recipe record.

    Conservative: defaults to False for positive tags (vegetarian, vegan,
    gluten_free, dairy_free, nut_free). Only sets True when we are confident.
    Ingredients must be non-empty for positive flags (can't claim vegan with
    no ingredient data).
    """
    text = _extract_text(data)
    ingredients = data.get("ingredients") or []
    has_ingredients = bool(ingredients) or bool(data.get("raw_ingredients_text"))

    has_meat = _contains_any(text, MEAT_KEYWORDS)
    has_seafood = _contains_any(text, SEAFOOD_KEYWORDS)
    has_shellfish = _contains_any(text, SHELLFISH_KEYWORDS)
    has_dairy = _contains_any(text, DAIRY_KEYWORDS)
    has_eggs = _contains_any(text, EGG_KEYWORDS)
    has_gluten = _contains_any(text, GLUTEN_KEYWORDS)
    has_nuts = _contains_any(text, NUT_KEYWORDS)

    # Positive flags: only set True if ingredients data present AND no blockers
    is_vegetarian = has_ingredients and not has_meat and not has_seafood
    is_vegan = has_ingredients and not has_meat and not has_seafood and not has_dairy and not has_eggs
    is_gluten_free = has_ingredients and not has_gluten
    is_dairy_free = has_ingredients and not has_dairy
    is_nut_free = has_ingredients and not has_nuts

    # Presence flags: True when ingredient is detected (regardless of ingredients completeness)
    contains_shellfish = has_shellfish
    contains_nuts = has_nuts

    return {
        "is_vegetarian": is_vegetarian,
        "is_vegan": is_vegan,
        "is_gluten_free": is_gluten_free,
        "is_dairy_free": is_dairy_free,
        "is_nut_free": is_nut_free,
        "contains_shellfish": contains_shellfish,
        "contains_nuts": contains_nuts,
    }


# ---------------------------------------------------------------------------
# Main batch loop
# ---------------------------------------------------------------------------

SKIP_STATUSES = {
    "dietary_tagged", "deterministic_enriched",
    "llm_enriched", "validated",
}

COURSE_TAGGED_STATUS = "course_tagged"


def run(
    batch_size: int = 1000,
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        log.error("Set SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.")
        sys.exit(1)

    sb: Client = create_client(url, key)

    total_processed = 0
    total_flagged = 0
    total_det_enriched = 0
    cursor: str | None = None
    start_time = time.time()
    last_log_at = 0

    log.info("Starting dietary-flags enrichment | batch=%d dry_run=%s limit=%s",
             batch_size, dry_run, limit)

    while True:
        query = (
            sb.table("recipes_open")
            .select("recipe_id, data, enrichment_status")
            .not_.in_("enrichment_status", list(SKIP_STATUSES))
            .order("recipe_id")
            .limit(batch_size)
        )
        if cursor:
            query = query.gt("recipe_id", cursor)

        response = query.execute()
        rows = response.data or []

        if not rows:
            log.info("No more rows to process.")
            break

        cursor = rows[-1]["recipe_id"]
        updates = []

        for row in rows:
            data: dict = row.get("data") or {}
            current_status: str = row.get("enrichment_status", "raw")

            flags = compute_dietary_flags(data)

            # Determine next enrichment_status
            if current_status == COURSE_TAGGED_STATUS:
                # Both course_tags and dietary_flags now written => fully deterministic
                next_status = "deterministic_enriched"
                total_det_enriched += 1
            else:
                # course_tags not yet written (or some other intermediate state)
                next_status = "dietary_tagged"

            updates.append({
                "recipe_id": row["recipe_id"],
                "data": {**data, "dietary_flags": flags},
                "enrichment_status": next_status,
            })
            total_flagged += 1

        total_processed += len(rows)

        if updates and not dry_run:
            sb.table("recipes_open").upsert(updates).execute()

        # Progress every 10k rows
        if total_processed - last_log_at >= 10_000 or not rows:
            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            remaining = (1_150_214 - total_processed) / rate if rate > 0 else float("inf")
            log.info(
                "Rows processed: %d | Flagged: %d | det_enriched: %d | "
                "Rate: %.0f r/s | ETA: %.0f s",
                total_processed, total_flagged, total_det_enriched, rate, remaining,
            )
            last_log_at = total_processed

        if limit and total_processed >= limit:
            log.info("Reached limit=%d, stopping.", limit)
            break

    log.info(
        "Done. Processed=%d | Flagged=%d | det_enriched=%d | dry_run=%s",
        total_processed, total_flagged, total_det_enriched, dry_run,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich dietary_flags in recipes_open")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run(batch_size=args.batch_size, dry_run=args.dry_run, limit=args.limit)
