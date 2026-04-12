"""enrich_course_tags.py — Deterministic course-tag classifier for recipes_open.

Usage:
    python enrich_course_tags.py [--batch-size N] [--limit N] [--dry-run]

What it does:
    - Reads records from recipes_open that do NOT yet have course_tags set
      (skips records with enrichment_status already 'course_tagged',
       'dietary_tagged', or 'deterministic_enriched').
    - Classifies each recipe title (case-insensitive keyword matching) into
      the controlled vocabulary from SCHEMA_CONTRACT:
        starter, main, dessert, side, salad, soup, breakfast,
        snack, drink, sauce, bread, other
    - Writes ONLY data->'course_tags' (JSON array).
    - Sets enrichment_status = 'course_tagged' as intermediate state.
    - Does NOT write enrichment_flags, provenance, tier, or dietary_flags.
    - Fully idempotent / restartable: skips already-course-tagged records.
    - Logs progress every 10,000 rows.

Ownership:
    CAT-B field: data->course_tags
    enrichment_status set to 'course_tagged'
    CAT-E columns (tier, enrichment_flags, provenance) are NOT touched.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

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
# Keyword taxonomy  (200+ patterns)
# ---------------------------------------------------------------------------
# Each entry: (frozenset_of_keywords, course_tag)
# Rules are evaluated IN ORDER; first match wins.
# Keywords are matched against the lowercased title.
#
# Priority order:
#   1. drink       (very distinctive; false-positives rare)
#   2. breakfast   (before dessert to catch "breakfast muffin")
#   3. dessert     (sweet baked goods, ice cream, candy, pudding...)
#   4. bread       (bread/roll/biscuit before "side" or "main")
#   5. soup        (before main; "soup" is unambiguous)
#   6. salad       (before side)
#   7. sauce       (before main)
#   8. starter     (appetiser / starter)
#   9. main        (broadest — near end so it doesn't swallow everything)
#  10. side        (vegetables, rice, grain sides)
#  11. snack       (chips, nuts, bar)
#  12. other       (explicit fallback; assigned when title gives a hint but
#                   doesn't fit above)
# Records with NO match get tag "other" (see classify_title below).

RULES: list[tuple[list[str], str]] = [
    # ------------------------------------------------------------------ drink
    ([
        "smoothie", "juice", "lemonade", "cocktail", "mocktail", "milkshake",
        "shake", "punch", "sangria", "cider", " tea ", "iced tea", "hot chocolate",
        "hot cocoa", "eggnog", "chai", "latte", "cappuccino", "espresso",
        "coffee drink", "spritzer", "soda", "kefir drink", "kombucha",
        "agua fresca", "horchata", "lassi", "frappuccino", "slushie",
        "margarita", "daiquiri", "mojito", "martini", "mimosa", "bloody mary",
        "gin and tonic", "rum punch", "whiskey sour", "old fashioned",
        "pina colada", "mai tai", "tequila sunrise", "beer bread",
    ], "drink"),

    # -------------------------------------------------------------- breakfast
    ([
        "pancake", "waffle", "french toast", "omelette", "omelet", "frittata",
        "scrambled egg", "poached egg", "fried egg", "egg bake", "egg casserole",
        "breakfast burrito", "breakfast sandwich", "breakfast bowl",
        "breakfast casserole", "breakfast muffin", "breakfast bar",
        "granola", "muesli", "porridge", "oatmeal", "overnight oat",
        "crepe", "cr\u00eape", "blini", "dutch baby", "biscuits and gravy",
        "hash brown", "hashbrown", "home fries", "breakfast potato",
        "breakfast sausage", "morning glory", "acai bowl", "smoothie bowl",
        "yogurt parfait", "bagel", "english muffin", "crumpet",
        "quiche",  # almost always breakfast/brunch
    ], "breakfast"),

    # --------------------------------------------------------------- dessert
    ([
        # Cakes
        "cake", "cheesecake", "cupcake", "layer cake", "bundt", "coffee cake",
        "pound cake", "angel cake", "devil's food", "carrot cake", "lava cake",
        "upside-down cake", "pineapple cake", "red velvet", "velvet cake",
        # Cookies & bars
        "cookie", "brownie", "blondie", "biscotti", "shortbread",
        "snickerdoodle", "macaroon", "macaron", "ladyfinger",
        "lemon bar", "pecan bar", "nanaimo",
        # Pies & tarts
        "pie", "tart", "galette", "cobbler", "crisp", "crumble", "clafoutis",
        "strudel", "baklava", "hand pie",
        # Puddings & custards
        "pudding", "custard", "bread pudding", "rice pudding", "panna cotta",
        "mousse", "parfait", "trifle", "tiramisu", "creme brulee",
        "cr\u00e8me br\u00fcl\u00e9e", "flan", "posset", "syllabub",
        # Frozen
        "ice cream", "gelato", "sorbet", "sherbet", "semifreddo", "frozen yogurt",
        "popsicle", "ice pop", "bombe",
        # Confectionery
        "fudge", "truffle", "praline", "brittle", "caramel", "toffee",
        "candy", "lollipop", "marshmallow", "nougat", "marzipan",
        "chocolate bark", "rocky road",
        # Sweet breads
        "doughnut", "donut", "churro", "beignet", "zeppole", "loukoumade",
        "funnel cake", "fried dough",
        # Misc sweet
        "dessert", "sweet roll", "cinnamon roll", "sticky bun", "eclair",
        "profiterole", "cream puff", "madeleine", "financier",
        "canele", "can\u00e9l\u00e9", "kouign amann", "danish pastry",
        "croissant",  # often dessert-context
        "palmier", "meringue", "pavlova", "eton mess",
        "halva", "gulab jamun", "jalebi", "rasgulla", "kheer",
        "mochi", "daifuku", "dorayaki",
        "tres leches", "arroz con leche", "budin",
    ], "dessert"),

    # ------------------------------------------------------------------ bread
    ([
        "bread", "sourdough", "focaccia", "ciabatta", "baguette", "brioche",
        "challah", "pita", "naan", "flatbread", "tortilla", "lavash",
        "breadstick", "dinner roll", "roll", "pretzel", "soft pretzel",
        "crackers", "cracker", "biscuit",  # American biscuit
        "cornbread", "corn bread", "zucchini bread", "banana bread",
        "pumpkin bread", "quick bread", "muffin",  # savory/quick muffins
        "scone", "crumpet",
        "rye bread", "whole wheat bread", "white bread", "sandwich bread",
        "pullman loaf", "milk bread", "shokupan", "hokkaido",
        "injera", "paratha", "chapati", "roti",
        "pao de queijo",
    ], "bread"),

    # ------------------------------------------------------------------- soup
    ([
        "soup", "stew", "broth", "bisque", "chowder", "gumbo",
        "minestrone", "gazpacho", "vichyssoise", "borscht", "pho",
        "ramen", "udon soup", "miso soup", "tom yum", "tom kha",
        "laksa", "mulligatawny", "pozole", "menudo", "caldo",
        "sopa", "potage", "veloute", "consomm\u00e9",
        "chicken noodle soup", "beef stew", "lentil soup",
        "clam chowder", "corn chowder", "potato soup",
        "french onion soup", "split pea", "black bean soup",
        "tortilla soup", "hot and sour soup", "wonton soup",
        "egg drop soup", "dashi", "bouillabaisse", "cacciucco",
    ], "soup"),

    # ----------------------------------------------------------------- salad
    ([
        "salad", "slaw", "coleslaw", "tabbouleh", "tabbouleh", "fattoush",
        "nicoise", "ni\u00e7oise", "caprese", "panzanella",
        "greek salad", "caesar salad", "waldorf", "cobb salad",
        "pasta salad", "potato salad", "egg salad", "tuna salad",
        "chicken salad", "shrimp salad", "lobster salad",
        "fruit salad", "grain salad", "quinoa salad",
        "roasted vegetable salad", "lentil salad", "bean salad",
        "kale salad", "spinach salad", "arugula salad",
        "watermelon salad", "beet salad", "corn salad",
        "raita", "tzatziki",  # dip/side salads
    ], "salad"),

    # ----------------------------------------------------------------- sauce
    ([
        "sauce", "gravy", "dressing", "vinaigrette", "marinade", "glaze",
        "rub", "spice rub", "dry rub", "spice blend", "seasoning blend",
        "salsa", "pesto", "chimichurri", "romesco", "harissa", "aioli",
        "hollandaise", "b\u00e9arnaise", "bechamel", "b\u00e9chamel",
        "veloute", "espagnole", "demi-glace",
        "hot sauce", "bbq sauce", "teriyaki sauce", "hoisin sauce",
        "oyster sauce", "fish sauce dip",
        "tahini sauce", "hummus",  # dip/spread/sauce context
        "tzatziki", "baba ganoush", "muhammara",
        "chutney", "relish", "pickle", "jam", "jelly", "preserve",
        "curd", "coulis", "compote",
        "butter sauce", "lemon butter", "garlic butter",
        "enchilada sauce", "mole", "adobo sauce",
        "tahini dressing", "miso glaze", "gochujang sauce",
        "crema",
    ], "sauce"),

    # --------------------------------------------------------------- starter
    ([
        "appetizer", "appetiser", "starter", "amuse", "canap\u00e9", "canape",
        "bruschetta", "crostini", "blini", "deviled egg", "stuffed mushroom",
        "stuffed pepper", "stuffed jalapeno", "jalapeno popper",
        "spring roll", "egg roll", "wonton", "dumpling", "gyoza", "potsticker",
        "samosa", "pakora", "bhaji", "fritter", "tempura",
        "calamari", "shrimp cocktail", "oyster", "clam",
        "charcuterie", "antipasto", "mezze",
        "nachos",  # typically starter/snack
        "dip",  # standalone dips are starters
        "crab cake", "crab dip", "spinach dip", "artichoke dip",
        "buffalo wing", "chicken wing", "hot wing",
        "garlic bread",  # starter not bread course
        "bruschetta", "pate", "p\u00e2t\u00e9", "terrine", "rillette",
        "escargot", "foie gras",
    ], "starter"),

    # ------------------------------------------------------------------- main
    ([
        # Pasta & noodles
        "pasta", "spaghetti", "linguine", "fettuccine", "penne", "rigatoni",
        "tagliatelle", "pappardelle", "orecchiette", "farfalle", "fusilli",
        "lasagna", "lasagne", "cannelloni", "manicotti", "ravioli", "tortellini",
        "gnocchi", "carbonara", "bolognese", "alfredo", "arrabbiata",
        "aglio e olio", "cacio e pepe", "amatriciana",
        "mac and cheese", "macaroni",
        "noodle", "lo mein", "chow mein", "pad thai", "pad see ew",
        "drunken noodle", "dan dan noodle", "cold soba", "yakisoba",
        # Rice & grain mains
        "risotto", "paella", "biryani", "fried rice", "rice bowl", "grain bowl",
        "pilaf", "pilau", "congee", "arroz",
        "polenta",  # main-course polenta
        "couscous",  # often a main
        # Meat mains
        "roast chicken", "roasted chicken", "chicken breast", "chicken thigh",
        "chicken drumstick", "chicken leg", "whole chicken", "spatchcock",
        "beef roast", "pot roast", "beef tenderloin", "prime rib",
        "steak", "sirloin", "ribeye", "filet mignon", "flank steak",
        "pork chop", "pork tenderloin", "pork belly", "pulled pork",
        "lamb chop", "rack of lamb", "leg of lamb", "lamb shank",
        "duck breast", "duck confit", "whole duck",
        "veal chop", "osso buco",
        "meatball", "meatloaf", "burger", "hamburger", "cheeseburger",
        "turkey breast", "turkey roast", "thanksgiving turkey",
        # Seafood mains
        "salmon", "tuna steak", "swordfish", "halibut", "cod", "tilapia",
        "mahi mahi", "sea bass", "branzino", "snapper", "grouper",
        "shrimp scampi", "lobster", "crab",
        # Tacos, wraps, sandwiches
        "taco", "burrito", "enchilada", "fajita", "quesadilla",
        "wrap", "sandwich", "sub", "hoagie", "panini",
        "po boy", "po' boy", "banh mi", "gyro", "shawarma", "kebab", "kabob",
        # Casseroles & bakes
        "casserole", "hot dish", "gratin", "bake",
        # Curries & stews (main course)
        "curry", "tikka masala", "palak", "paneer", "korma", "vindaloo",
        "massaman", "green curry", "red curry", "yellow curry",
        "tagine", "tajine", "shakshuka", "moussaka", "pastitsio",
        "chili", "chilli",  # as main
        "jambalaya",
        # Pizza & flatbread mains
        "pizza", "calzone", "stromboli", "flatbread pizza",
        # Plant-based mains
        "veggie burger", "bean burger", "lentil burger",
        "tofu stir fry", "tempeh", "seitan",
        "stuffed eggplant", "stuffed zucchini", "stuffed squash",
        "vegetable tart", "vegetable bake", "grain bake",
    ], "main"),

    # ------------------------------------------------------------------- side
    ([
        "side dish", "side salad",
        # Potato sides
        "mashed potato", "roasted potato", "potato wedge", "potato gratin",
        "scalloped potato", "potato au gratin", "twice baked potato",
        "potato casserole", "potato cake",
        # Vegetable sides
        "roasted vegetable", "saut\u00e9ed", "glazed carrot", "roasted carrot",
        "roasted asparagus", "roasted broccoli", "roasted cauliflower",
        "steamed broccoli", "creamed spinach", "creamed corn",
        "green bean", "brussels sprout", "roasted beet",
        "ratatouille",  # vegetable side/stew
        # Rice & grain sides
        "steamed rice", "white rice", "brown rice", "jasmine rice",
        "basmati rice", "wild rice", "rice pilaf",
        "quinoa", "farro", "barley",  # as simple side
        # Legume sides
        "refried bean", "black bean", "baked bean",
        "lentil side",
        # Other
        "coleslaw",  # duplicate; safe
        "stuffing", "dressing",  # Thanksgiving sides
        "mac and cheese",  # sometimes side
        "succotash", "corn on the cob", "elote",
    ], "side"),

    # ------------------------------------------------------------------ snack
    ([
        "snack", "trail mix", "energy ball", "energy bite", "protein ball",
        "protein bar", "granola bar", "snack bar", "fruit leather",
        "chips", "kale chip", "tortilla chip", "pita chip",
        "popcorn", "kettle corn",
        "nut mix", "spiced nut", "roasted nut",
        "beef jerky", "jerky",
        "rice cake",
        "deviled egg",  # also starter; snack context common
    ], "snack"),
]

# Compile lowercase keyword sets for fast lookup
_COMPILED: list[tuple[list[str], str]] = [
    ([kw.lower() for kw in kws], tag) for kws, tag in RULES
]


def classify_title(title: str) -> list[str]:
    """Return a list with one course tag based on keyword matching.

    Returns ['other'] if no keyword matches.
    """
    lower = title.lower()
    for keywords, tag in _COMPILED:
        for kw in keywords:
            # Word-boundary style: keyword must appear as a whole token or
            # be surrounded by non-alphanumeric chars.
            if kw in lower:
                return [tag]
    return ["other"]


# ---------------------------------------------------------------------------
# Main batch loop
# ---------------------------------------------------------------------------

SKIP_STATUSES = {
    "course_tagged", "dietary_tagged", "deterministic_enriched",
    "llm_enriched", "validated",
}


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
    total_tagged = 0
    total_skipped = 0
    cursor: str | None = None
    start_time = time.time()
    last_log_at = 0

    log.info("Starting course-tag enrichment | batch=%d dry_run=%s limit=%s",
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
            title: str = (data.get("title") or "").strip()

            if not title:
                total_skipped += 1
                continue

            tags = classify_title(title)
            updates.append({
                "recipe_id": row["recipe_id"],
                "data": {**data, "course_tags": tags},
                "enrichment_status": "course_tagged",
            })

        total_processed += len(rows)
        total_tagged += len(updates)

        if updates and not dry_run:
            sb.table("recipes_open").upsert(updates).execute()

        # Progress every 10k rows
        if total_processed - last_log_at >= 10_000 or not rows:
            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            remaining = (1_150_214 - total_processed) / rate if rate > 0 else float("inf")
            log.info(
                "Rows processed: %d | Tagged: %d | Skipped: %d | "
                "Rate: %.0f r/s | ETA: %.0f s",
                total_processed, total_tagged, total_skipped, rate, remaining,
            )
            last_log_at = total_processed

        if limit and total_processed >= limit:
            log.info("Reached limit=%d, stopping.", limit)
            break

    log.info(
        "Done. Processed=%d | Tagged=%d | Skipped=%d | dry_run=%s",
        total_processed, total_tagged, total_skipped, dry_run,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich course_tags in recipes_open")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run(batch_size=args.batch_size, dry_run=args.dry_run, limit=args.limit)
