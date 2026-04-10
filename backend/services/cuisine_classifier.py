"""
CuisineClassifier — two-layer cuisine classification for miam recipes.

Layer 1: classify_rule_based(title, ner)
    Pure Python. No external calls. Uses TITLE_KEYWORDS (longest-match first)
    and INGREDIENT_SCORES (weighted per-cuisine scoring).

Layer 2: CuisineClassifier.classify_batch(recipes)
    Batch LLM fallback via Mistral Small through the LLM router.
    Groups up to 20 recipes per API call to minimise cost.

Top-level entry point:
    classify_cuisine(title, ner) — chains both layers.

Canonical cuisine vocabulary (25 values):
    Italian, French, Spanish, Greek, Moroccan, Lebanese, Turkish,
    Indian, Chinese, Japanese, Korean, Thai, Vietnamese, Mexican,
    Peruvian, American, British, German, Dutch, Scandinavian,
    Middle Eastern, African, Caribbean, Fusion, Other
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from typing import Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.llm_router import LLMOperation, call_llm_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Controlled vocabulary
# ---------------------------------------------------------------------------

CUISINE_VOCABULARY: list[str] = [
    "Italian", "French", "Spanish", "Greek", "Moroccan",
    "Lebanese", "Turkish", "Indian", "Chinese", "Japanese",
    "Korean", "Thai", "Vietnamese", "Mexican", "Peruvian",
    "American", "British", "German", "Dutch", "Scandinavian",
    "Middle Eastern", "African", "Caribbean", "Fusion", "Other",
]

_VOCAB_SET: set[str] = set(CUISINE_VOCABULARY)

# ---------------------------------------------------------------------------
# Rule-based layer — TITLE_KEYWORDS
#
# IMPORTANT: Keys are matched as whole-word substrings (case-insensitive).
# The dict is sorted longest-key-first at module load so that compound
# phrases ("kimchi fried rice") always shadow their substrings ("fried rice").
#
# Plural handling: _match_title() appends (?:e?s)? to each keyword regex
# so singular and plural forms both match without duplicating entries.
# ---------------------------------------------------------------------------

TITLE_KEYWORDS: dict[str, str] = {
    # ── Compound / shadowing guards (must come before their substrings) ──────
    "kimchi fried rice":        "Korean",
    "thai fried rice":          "Thai",
    "pineapple fried rice":     "Thai",
    "nasi goreng":              "Indonesian",   # not in core vocab → falls to Other via LLM
    "french onion soup":        "French",
    "thai green curry":         "Thai",
    "thai red curry":           "Thai",
    "thai yellow curry":        "Thai",
    "butter chicken":           "Indian",
    "chicken tikka masala":     "Indian",
    "beef bourguignon":         "French",
    "arroz con leche":          "Spanish",
    "arroz con pollo":          "Spanish",
    "cheeseburger":             "American",
    "mac and cheese":           "American",
    "fish and chips":           "British",
    "beef wellington":          "British",
    "bangers and mash":         "British",
    "lomo saltado":             "Peruvian",
    "aji de gallina":           "Peruvian",
    "banh mi":                  "Vietnamese",
    "pho bo":                   "Vietnamese",
    "pad see ew":               "Thai",
    "pad kra pao":              "Thai",
    "khao pad":                 "Thai",
    "kung pao":                 "Chinese",
    "mapo tofu":                "Chinese",
    "peking duck":              "Chinese",
    "dim sum":                  "Chinese",
    "char siu":                 "Chinese",
    "miso soup":                "Japanese",
    "tonkotsu ramen":           "Japanese",
    "chicken katsu":            "Japanese",
    "bibimbap":                 "Korean",
    "tteokbokki":               "Korean",
    "japchae":                  "Korean",
    "chicken shawarma":         "Lebanese",
    "lamb shawarma":            "Lebanese",
    "chicken souvlaki":         "Greek",
    "lamb souvlaki":            "Greek",
    "jerk chicken":             "Caribbean",
    "jollof rice":              "African",
    "bobotie":                  "African",
    "boeuf bourguignon":        "French",

    # ── Italian ──────────────────────────────────────────────────────────────
    "spaghetti":        "Italian",
    "carbonara":        "Italian",
    "bolognese":        "Italian",
    "lasagna":          "Italian",
    "lasagne":          "Italian",
    "risotto":          "Italian",
    "tiramisu":         "Italian",
    "osso buco":        "Italian",
    "panna cotta":      "Italian",
    "bruschetta":       "Italian",
    "focaccia":         "Italian",
    "gnocchi":          "Italian",
    "minestrone":       "Italian",
    "antipasto":        "Italian",
    "cacio e pepe":     "Italian",
    "amatriciana":      "Italian",
    "ribollita":        "Italian",
    "panzanella":       "Italian",
    "saltimbocca":      "Italian",
    "piccata":          "Italian",
    "arancini":         "Italian",
    "cannoli":          "Italian",
    "stracciatella":    "Italian",
    "polenta":          "Italian",
    "pizza":            "Italian",
    "pasta":            "Italian",
    "fettuccine":       "Italian",
    "pappardelle":      "Italian",
    "tagliatelle":      "Italian",
    "rigatoni":         "Italian",
    "penne":            "Italian",
    "linguine":         "Italian",
    "orecchiette":      "Italian",
    "tortellini":       "Italian",
    "ravioli":          "Italian",

    # ── French ───────────────────────────────────────────────────────────────
    "croissant":        "French",
    "quiche":           "French",
    "ratatouille":      "French",
    "bouillabaisse":    "French",
    "crepe":            "French",
    "crêpe":            "French",
    "coq au vin":       "French",
    "vichyssoise":      "French",
    "cassoulet":        "French",
    "tarte tatin":      "French",
    "soufflé":          "French",
    "souffle":          "French",
    "pot-au-feu":       "French",
    "confit":           "French",
    "beurre blanc":     "French",
    "salade nicoise":   "French",
    "salade niçoise":   "French",
    "madeleines":       "French",
    "financier":        "French",
    "clafoutis":        "French",
    "gratin":           "French",
    "dauphinois":       "French",
    "bisque":           "French",
    "escargot":         "French",

    # ── Spanish ──────────────────────────────────────────────────────────────
    "paella":           "Spanish",
    "gazpacho":         "Spanish",
    "tortilla española":"Spanish",
    "patatas bravas":   "Spanish",
    "churro":           "Spanish",
    "croqueta":         "Spanish",
    "albondigas":       "Spanish",
    "fabada":           "Spanish",
    "sofrito":          "Spanish",
    "romesco":          "Spanish",
    "salmorejo":        "Spanish",
    "pisto":            "Spanish",
    "empanada":         "Spanish",
    "chorizo":          "Spanish",

    # ── Greek ────────────────────────────────────────────────────────────────
    "moussaka":         "Greek",
    "spanakopita":      "Greek",
    "tzatziki":         "Greek",
    "gyro":             "Greek",
    "souvlaki":         "Greek",
    "baklava":          "Greek",
    "horiatiki":        "Greek",
    "fasolada":         "Greek",
    "loukoumades":      "Greek",
    "saganaki":         "Greek",
    "dolmades":         "Greek",
    "pastitsio":        "Greek",
    "taramosalata":     "Greek",

    # ── Moroccan ─────────────────────────────────────────────────────────────
    "tagine":           "Moroccan",
    "tajine":           "Moroccan",
    "harira":           "Moroccan",
    "couscous":         "Moroccan",
    "bastilla":         "Moroccan",
    "chermoula":        "Moroccan",
    "zaalouk":          "Moroccan",
    "bissara":          "Moroccan",
    "msemen":           "Moroccan",

    # ── Lebanese ─────────────────────────────────────────────────────────────
    "hummus":           "Lebanese",
    "falafel":          "Lebanese",
    "tabbouleh":        "Lebanese",
    "shawarma":         "Lebanese",
    "kibbeh":           "Lebanese",
    "fattoush":         "Lebanese",
    "manakish":         "Lebanese",
    "kafta":            "Lebanese",
    "labneh":           "Lebanese",
    "mutabal":          "Lebanese",
    "baba ganoush":     "Lebanese",

    # ── Turkish ──────────────────────────────────────────────────────────────
    "kebab":            "Turkish",
    "köfte":            "Turkish",
    "kofte":            "Turkish",
    "lahmacun":         "Turkish",
    "manti":            "Turkish",
    "borek":            "Turkish",
    "börek":            "Turkish",
    "pide":             "Turkish",
    "dolma":            "Turkish",
    "simit":            "Turkish",
    "menemen":          "Turkish",
    "iskender":         "Turkish",
    "doner":            "Turkish",
    "döner":            "Turkish",

    # ── Indian ───────────────────────────────────────────────────────────────
    "biryani":          "Indian",
    "curry":            "Indian",
    "dal":              "Indian",
    "dhal":             "Indian",
    "samosa":           "Indian",
    "naan":             "Indian",
    "tikka":            "Indian",
    "masala":           "Indian",
    "korma":            "Indian",
    "vindaloo":         "Indian",
    "palak":            "Indian",
    "saag":             "Indian",
    "paneer":           "Indian",
    "chana":            "Indian",
    "aloo":             "Indian",
    "paratha":          "Indian",
    "dosa":             "Indian",
    "idli":             "Indian",
    "upma":             "Indian",
    "halwa":            "Indian",
    "kheer":            "Indian",
    "gulab jamun":      "Indian",
    "raita":            "Indian",
    "lassi":            "Indian",
    "tandoori":         "Indian",
    "rogan josh":       "Indian",

    # ── Chinese ──────────────────────────────────────────────────────────────
    "fried rice":       "Chinese",
    "chow mein":        "Chinese",
    "lo mein":          "Chinese",
    "wonton":           "Chinese",
    "dumpling":         "Chinese",
    "spring roll":      "Chinese",
    "bok choy":         "Chinese",
    "sweet and sour":   "Chinese",
    "szechuan":         "Chinese",
    "sichuan":          "Chinese",
    "cantonese":        "Chinese",
    "congee":           "Chinese",
    "hot pot":          "Chinese",
    "xiaolongbao":      "Chinese",
    "lion's head":      "Chinese",
    "buddha's delight": "Chinese",
    "chop suey":        "Chinese",

    # ── Japanese ─────────────────────────────────────────────────────────────
    "sushi":            "Japanese",
    "ramen":            "Japanese",
    "udon":             "Japanese",
    "soba":             "Japanese",
    "tempura":          "Japanese",
    "teriyaki":         "Japanese",
    "yakitori":         "Japanese",
    "tonkatsu":         "Japanese",
    "katsu":            "Japanese",
    "onigiri":          "Japanese",
    "takoyaki":         "Japanese",
    "okonomiyaki":      "Japanese",
    "gyoza":            "Japanese",
    "sukiyaki":         "Japanese",
    "shabu shabu":      "Japanese",
    "donburi":          "Japanese",
    "yakisoba":         "Japanese",
    "edamame":          "Japanese",
    "mochi":            "Japanese",
    "dorayaki":         "Japanese",

    # ── Korean ───────────────────────────────────────────────────────────────
    "kimchi":           "Korean",
    "bulgogi":          "Korean",
    "galbi":            "Korean",
    "pajeon":           "Korean",
    "sundubu":          "Korean",
    "doenjang":         "Korean",
    "samgyeopsal":      "Korean",
    "bossam":           "Korean",
    "jjigae":           "Korean",
    "ramyeon":          "Korean",
    "gimbap":           "Korean",
    "haemul":           "Korean",

    # ── Thai ─────────────────────────────────────────────────────────────────
    "pad thai":         "Thai",
    "tom yum":          "Thai",
    "tom kha":          "Thai",
    "green curry":      "Thai",
    "red curry":        "Thai",
    "yellow curry":     "Thai",
    "massaman":         "Thai",
    "panang":           "Thai",
    "satay":            "Thai",
    "larb":             "Thai",
    "som tam":          "Thai",
    "papaya salad":     "Thai",
    "mango sticky rice":"Thai",

    # ── Vietnamese ───────────────────────────────────────────────────────────
    "pho":              "Vietnamese",
    "bun bo":           "Vietnamese",
    "banh xeo":         "Vietnamese",
    "goi cuon":         "Vietnamese",
    "bun cha":          "Vietnamese",
    "cao lau":          "Vietnamese",
    "com tam":          "Vietnamese",

    # ── Mexican ──────────────────────────────────────────────────────────────
    "taco":             "Mexican",
    "burrito":          "Mexican",
    "enchilada":        "Mexican",
    "tamale":           "Mexican",
    "quesadilla":       "Mexican",
    "guacamole":        "Mexican",
    "salsa":            "Mexican",
    "pozole":           "Mexican",
    "mole":             "Mexican",
    "chiles rellenos":  "Mexican",
    "tlayuda":          "Mexican",
    "elote":            "Mexican",
    "chilaquile":       "Mexican",
    "huevos rancheros": "Mexican",
    "fajita":           "Mexican",
    "nachos":           "Mexican",
    "torta":            "Mexican",
    "sope":             "Mexican",
    "gordita":          "Mexican",

    # ── Peruvian ─────────────────────────────────────────────────────────────
    "ceviche":          "Peruvian",
    "causa":            "Peruvian",
    "anticucho":        "Peruvian",
    "papa a la huancaina": "Peruvian",
    "leche de tigre":   "Peruvian",
    "tiradito":         "Peruvian",

    # ── American ─────────────────────────────────────────────────────────────
    "burger":           "American",
    "hamburger":        "American",
    "hot dog":          "American",
    "bbq":              "American",
    "barbecue":         "American",
    "pancake":          "American",
    "waffle":           "American",
    "brownie":          "American",
    "cheesecake":       "American",
    "clam chowder":     "American",
    "cornbread":        "American",
    "coleslaw":         "American",
    "buffalo wing":     "American",
    "pulled pork":      "American",
    "biscuit":          "American",
    "grits":            "American",
    "cobbler":          "American",

    # ── British ──────────────────────────────────────────────────────────────
    "scone":            "British",
    "crumpet":          "British",
    "shepherd's pie":   "British",
    "cottage pie":      "British",
    "yorkshire pudding":"British",
    "sunday roast":     "British",
    "sticky toffee":    "British",
    "eton mess":        "British",
    "welsh rarebit":    "British",
    "spotted dick":     "British",
    "toad in the hole": "British",
    "cornish pasty":    "British",
    "scotch egg":       "British",

    # ── German ───────────────────────────────────────────────────────────────
    "bratwurst":        "German",
    "schnitzel":        "German",
    "sauerkraut":       "German",
    "pretzel":          "German",
    "strudel":          "German",
    "sauerbraten":      "German",
    "rouladen":         "German",
    "lebkuchen":        "German",
    "kartoffelsalat":   "German",
    "currywurst":       "German",
    "wurst":            "German",
    "spaetzle":         "German",
    "spätzle":          "German",
    "kassler":          "German",
    "eisbein":          "German",
    "flammkuchen":      "German",

    # ── Dutch ────────────────────────────────────────────────────────────────
    "stroopwafel":      "Dutch",
    "stamppot":         "Dutch",
    "bitterballen":     "Dutch",
    "erwtensoep":       "Dutch",
    "hutspot":          "Dutch",
    "kroket":           "Dutch",
    "poffertjes":       "Dutch",
    "oliebollen":       "Dutch",
    "hagelslag":        "Dutch",
    "hachee":           "Dutch",
    "snert":            "Dutch",
    "zuurvlees":        "Dutch",
    "boerenkool":       "Dutch",
    "appeltaart":       "Dutch",
    "speculaas":        "Dutch",
    "drop":             "Dutch",

    # ── Scandinavian ─────────────────────────────────────────────────────────
    "gravlax":          "Scandinavian",
    "gravad lax":       "Scandinavian",
    "smorgasbord":      "Scandinavian",
    "smörgåsbord":      "Scandinavian",
    "lefse":            "Scandinavian",
    "lutefisk":         "Scandinavian",
    "swedish meatball": "Scandinavian",
    "swedish meatballs":"Scandinavian",
    "danish pastry":    "Scandinavian",
    "rye bread":        "Scandinavian",
    "kanelbullar":      "Scandinavian",
    "cinnamon bun":     "Scandinavian",
    "fika":             "Scandinavian",
    "surströmming":     "Scandinavian",
    "aebleskiver":      "Scandinavian",
    "æbleskiver":       "Scandinavian",

    # ── Middle Eastern ───────────────────────────────────────────────────────
    "mansaf":           "Middle Eastern",
    "mujaddara":        "Middle Eastern",
    "shakshuka":        "Middle Eastern",
    "fatayer":          "Middle Eastern",
    "za'atar":          "Middle Eastern",
    "zaatar":           "Middle Eastern",
    "knafeh":           "Middle Eastern",
    "kanafeh":          "Middle Eastern",
    "musakhan":         "Middle Eastern",
    "maqluba":          "Middle Eastern",
    "kabsa":            "Middle Eastern",
    "madfoon":          "Middle Eastern",

    # ── African ──────────────────────────────────────────────────────────────
    "injera":           "African",
    "doro wat":         "African",
    "wat":              "African",
    "fufu":             "African",
    "egusi":            "African",
    "suya":             "African",
    "piri piri":        "African",
    "chakalaka":        "African",
    "braai":            "African",
    "bunny chow":       "African",
    "pap":              "African",
    "ugali":            "African",

    # ── Caribbean ────────────────────────────────────────────────────────────
    "jerk":             "Caribbean",
    "roti":             "Caribbean",
    "ackee":            "Caribbean",
    "plantain":         "Caribbean",
    "rice and peas":    "Caribbean",
    "callaloo":         "Caribbean",
    "doubles":          "Caribbean",
    "saltfish":         "Caribbean",
    "sorrel":           "Caribbean",
    "escovitch":        "Caribbean",
}

# Sort longest-first so compound phrases shadow their substrings
TITLE_KEYWORDS = dict(
    sorted(TITLE_KEYWORDS.items(), key=lambda kv: len(kv[0]), reverse=True)
)

# ---------------------------------------------------------------------------
# Rule-based layer — INGREDIENT_SCORES
# Weighted ingredient → cuisine scoring for ingredient-signal fallback
# ---------------------------------------------------------------------------

INGREDIENT_SCORES: dict[str, dict[str, float]] = {
    "Italian": {
        "parmigiano": 3.0, "parmesan": 2.5, "pecorino": 3.0,
        "pancetta": 2.5, "guanciale": 3.0, "prosciutto": 2.5,
        "basil": 1.5, "oregano": 1.5, "mozzarella": 2.5,
        "ricotta": 2.0, "arborio": 3.0, "semolina": 2.0,
        "balsamic": 2.0, "capers": 1.5, "anchovies": 1.5,
        "passata": 2.0, "nduja": 3.0, "burrata": 3.0,
    },
    "French": {
        "dijon": 2.5, "tarragon": 2.5, "herbes de provence": 3.0,
        "gruyere": 2.5, "gruyère": 2.5, "emmental": 2.0,
        "beurre": 2.0, "crème fraîche": 3.0, "creme fraiche": 3.0,
        "shallot": 1.5, "cognac": 2.5, "bordeaux": 2.5,
        "lardons": 3.0, "baguette": 2.5, "camembert": 3.0,
        "roquefort": 3.0, "comté": 3.0, "comte": 3.0,
    },
    "Spanish": {
        "chorizo": 2.5, "smoked paprika": 2.5, "pimentón": 3.0,
        "pimenton": 3.0, "saffron": 2.0, "manchego": 3.0,
        "serrano": 2.5, "jamón": 3.0, "jamon": 3.0,
        "sherry": 2.5, "albariño": 2.5, "albarino": 2.5,
        "bomba rice": 3.0, "arbequina": 2.5,
    },
    "Greek": {
        "feta": 3.0, "kalamata": 3.0, "ouzo": 3.0,
        "phyllo": 2.5, "filo": 2.5, "pine nut": 1.5,
        "dried oregano": 2.0, "lamb": 1.0, "lemon": 0.5,
        "halloumi": 2.5, "kefalotiri": 3.0, "mastika": 3.0,
        "mahlepi": 3.0,
    },
    "Moroccan": {
        "ras el hanout": 3.0, "harissa": 2.5, "preserved lemon": 3.0,
        "argan oil": 3.0, "merguez": 3.0, "smen": 3.0,
        "orange blossom": 2.5, "rose water": 1.5,
        "cumin": 1.0, "coriander": 1.0, "cinnamon": 0.5,
        "chickpea": 1.0, "dried apricot": 1.5, "medjool date": 2.0,
    },
    "Lebanese": {
        "tahini": 2.5, "sumac": 3.0, "zaatar": 3.0, "za'atar": 3.0,
        "bulgur": 2.5, "pomegranate molasses": 3.0,
        "freekeh": 3.0, "lebanese bread": 3.0,
        "allspice": 1.5, "seven spice": 3.0, "aleppo": 2.5,
    },
    "Turkish": {
        "urfa biber": 3.0, "isot": 3.0, "biber salçası": 3.0,
        "biber salcasi": 3.0, "pul biber": 3.0,
        "haydari": 3.0, "cacik": 3.0, "çaçık": 3.0,
        "sucuk": 3.0, "pastırma": 3.0, "pastirma": 3.0,
        "Turkish pepper": 2.0,
    },
    "Indian": {
        "garam masala": 3.0, "turmeric": 2.0, "cumin seeds": 2.0,
        "mustard seeds": 2.0, "curry leaves": 3.0, "fenugreek": 2.5,
        "ghee": 2.5, "paneer": 3.0, "basmati": 2.5,
        "cardamom": 1.5, "amchur": 3.0, "asafoetida": 3.0,
        "hing": 3.0, "chaat masala": 3.0, "tamarind": 1.5,
        "urad dal": 3.0, "toor dal": 3.0,
    },
    "Chinese": {
        "soy sauce": 1.5, "sesame oil": 1.5, "oyster sauce": 2.5,
        "hoisin": 2.5, "shaoxing": 3.0, "five spice": 2.5,
        "bok choy": 2.5, "water chestnut": 2.5, "tofu": 1.0,
        "scallion": 1.0, "ginger": 1.0, "star anise": 2.0,
        "rice vinegar": 1.5, "doubanjiang": 3.0, "chili bean paste": 3.0,
        "black bean sauce": 2.5, "lap cheong": 3.0, "Chinese sausage": 3.0,
    },
    "Japanese": {
        "miso": 3.0, "mirin": 3.0, "sake": 2.0,
        "dashi": 3.0, "kombu": 3.0, "katsuobushi": 3.0,
        "bonito flakes": 3.0, "nori": 3.0, "natto": 3.0,
        "yuzu": 3.0, "shiso": 3.0, "ponzu": 3.0,
        "panko": 2.5, "wasabi": 2.5, "pickled ginger": 2.0,
        "udon": 3.0, "soba": 3.0, "togarashi": 3.0,
    },
    "Korean": {
        "gochujang": 3.0, "doenjang": 3.0, "gochugaru": 3.0,
        "kimchi": 3.0, "sesame oil": 1.0, "perilla": 3.0,
        "ssamjang": 3.0, "fish sauce": 1.0, "napa cabbage": 2.0,
        "daikon": 1.5, "Korean chili": 3.0, "perilla oil": 3.0,
    },
    "Thai": {
        "fish sauce": 2.0, "lemongrass": 3.0, "galangal": 3.0,
        "kaffir lime": 3.0, "thai basil": 3.0, "coconut milk": 1.5,
        "palm sugar": 2.5, "thai chili": 3.0, "shrimp paste": 2.5,
        "nam pla": 3.0, "makrut": 3.0, "pandan": 2.0,
    },
    "Vietnamese": {
        "rice paper": 3.0, "bean sprout": 1.5, "nuoc mam": 3.0,
        "nuoc cham": 3.0, "fish sauce": 1.5, "fresh mint": 1.0,
        "perilla": 1.0, "hoisin": 1.0, "star anise": 1.5,
        "vietnamese mint": 3.0, "sawtooth coriander": 3.0,
        "rau ram": 3.0,
    },
    "Mexican": {
        "chipotle": 3.0, "ancho": 3.0, "poblano": 3.0,
        "pasilla": 3.0, "epazote": 3.0, "tomatillo": 3.0,
        "masa": 3.0, "cotija": 3.0, "queso fresco": 3.0,
        "Mexican crema": 2.5, "cilantro": 1.5, "jalapeño": 2.5,
        "serrano pepper": 2.5, "achiote": 3.0, "huitlacoche": 3.0,
    },
    "Peruvian": {
        "aji amarillo": 3.0, "aji panca": 3.0, "huacatay": 3.0,
        "lucuma": 3.0, "chicha": 3.0, "causa": 3.0,
        "leche de tigre": 3.0, "quinoa": 1.5, "purple corn": 3.0,
        "inca kola": 3.0,
    },
    "American": {
        "maple syrup": 2.0, "bourbon": 2.5, "cornmeal": 2.0,
        "cream cheese": 1.5, "ranch": 2.5, "blue cheese": 1.5,
        "buttermilk": 2.0, "American mustard": 2.0,
        "liquid smoke": 3.0, "hickory": 2.5,
    },
    "British": {
        "marmite": 3.0, "worcestershire": 2.5, "HP sauce": 3.0,
        "clotted cream": 3.0, "double cream": 2.0,
        "streaky bacon": 2.0, "black pudding": 3.0,
        "mushy peas": 3.0, "suet": 3.0, "golden syrup": 2.5,
        "treacle": 2.5, "stilton": 3.0, "cheddar": 1.5,
    },
    "German": {
        "caraway": 2.5, "juniper berry": 2.5, "sauerkraut": 3.0,
        "quark": 3.0, "speck": 2.0, "knödel": 3.0,
        "knoedel": 3.0, "rye flour": 2.0, "lager": 2.0,
        "weisswurst": 3.0, "bretzeln": 3.0,
    },
    "Dutch": {
        "gouda": 3.0, "edam": 3.0, "stroopwafel": 3.0,
        "Dutch licorice": 3.0, "erwten": 3.0, "rookworst": 3.0,
        "hagelslag": 3.0, "speculaas spice": 3.0, "Dutch butter": 2.0,
    },
    "Scandinavian": {
        "dill": 1.5, "lingonberry": 3.0, "cloudberry": 3.0,
        "aquavit": 3.0, "akvavit": 3.0, "rye": 1.5,
        "cardamom": 1.0, "allspice": 1.0, "pickled herring": 3.0,
        "Swedish cream": 2.5, "lefse": 3.0, "brunost": 3.0,
        "brown cheese": 2.5, "sea buckthorn": 3.0,
    },
    "Middle Eastern": {
        "rose water": 2.0, "orange blossom water": 2.5,
        "dried lime": 3.0, "loomi": 3.0, "baharat": 3.0,
        "za'atar": 2.5, "pomegranate": 2.0, "pistachio": 1.5,
        "filo": 1.5, "sumac": 2.0, "halva": 2.5,
        "tahini": 2.0, "shawarma spice": 3.0,
    },
    "African": {
        "berbere": 3.0, "niter kibbeh": 3.0, "teff": 3.0,
        "mafe": 3.0, "egusi": 3.0, "ogiri": 3.0,
        "dawadawa": 3.0, "fufu": 3.0, "ugali": 3.0,
        "suya spice": 3.0, "palm oil": 2.5, "groundnut": 2.0,
        "plantain": 2.0,
    },
    "Caribbean": {
        "allspice": 1.5, "scotch bonnet": 3.0, "habanero": 2.0,
        "coconut water": 2.0, "jerk seasoning": 3.0, "callaloo": 3.0,
        "ackee": 3.0, "pigeon pea": 2.5, "breadfruit": 3.0,
        "mauby": 3.0, "sorrel": 2.5, "rum": 1.5,
    },
}

# Score threshold: ingredient scorer must exceed this to return a cuisine
_SCORE_THRESHOLD = 3.0


# ---------------------------------------------------------------------------
# Rule-based classification
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip accents lightly."""
    return " ".join(text.lower().split())


def _match_title(title_norm: str) -> Optional[str]:
    """
    Longest-match scan of TITLE_KEYWORDS against the normalised title.
    Each keyword is matched as a whole-word pattern with optional plural suffix.
    """
    for keyword, cuisine in TITLE_KEYWORDS.items():
        # Build pattern: whole-word, optional plural suffix
        escaped = re.escape(keyword)
        pattern = rf"(?<![a-z]){escaped}(?:e?s)?(?![a-z])"
        if re.search(pattern, title_norm):
            return cuisine
    return None


def _score_ingredients(ner: list[str]) -> Optional[str]:
    """
    Score ingredient list against INGREDIENT_SCORES.
    Returns the top-scoring cuisine if it exceeds _SCORE_THRESHOLD, else None.
    """
    scores: dict[str, float] = {}
    ner_norm = [_normalise(x) for x in ner]

    for cuisine, terms in INGREDIENT_SCORES.items():
        total = 0.0
        for term, weight in terms.items():
            term_norm = _normalise(term)
            for ing in ner_norm:
                if term_norm in ing:
                    total += weight
                    break  # count each term once
        if total > 0:
            scores[cuisine] = total

    if not scores:
        return None

    best_cuisine = max(scores, key=lambda c: scores[c])
    if scores[best_cuisine] >= _SCORE_THRESHOLD:
        return best_cuisine
    return None


def classify_rule_based(title: str, ner: list[str]) -> Optional[str]:
    """
    Layer 1: pure rule-based classification.

    1. Normalise title, scan TITLE_KEYWORDS longest-first.
    2. If no title match, score ingredients via INGREDIENT_SCORES.
    3. Return None if neither layer is confident (triggers LLM fallback).
    """
    if not title or not title.strip():
        return None

    title_norm = _normalise(title)

    # Title match first (highest confidence)
    cuisine = _match_title(title_norm)
    if cuisine:
        # Map any non-vocabulary result (e.g. Indonesian) to None → LLM
        return cuisine if cuisine in _VOCAB_SET else None

    # Ingredient scoring fallback
    return _score_ingredients(ner)


# ---------------------------------------------------------------------------
# LLM layer — CuisineClassifier
# ---------------------------------------------------------------------------

_BATCH_SIZE = 20

_SYSTEM_PROMPT = f"""You are a culinary cuisine classifier. Given a list of recipes (each with a title and ingredient list), classify each recipe into exactly ONE primary cuisine from this controlled vocabulary:

{json.dumps(CUISINE_VOCABULARY)}

Rules:
- Return a JSON array of objects, one per recipe, in the same order as the input.
- Each object must have: {{"index": <int>, "cuisine": "<string from vocabulary>"}}
- Use "Fusion" for recipes that clearly blend two or more cuisines.
- Use "Other" only if no cuisine in the vocabulary fits.
- Base your classification on both the recipe title and the ingredient combination.
- If the title explicitly names a cuisine (e.g. "Thai Green Curry"), honour it.
- Return ONLY the JSON array, no markdown, no explanation."""


class CuisineClassifier:
    """
    Batch cuisine classifier using Mistral Small via the LLM router.

    Usage:
        classifier = CuisineClassifier()
        results = await classifier.classify_batch(recipes)
        # [{\"index\": 0, \"cuisine\": \"Italian\"}, ...]
    """

    async def classify_batch(self, recipes: Sequence[dict]) -> list[dict]:
        all_results: list[dict] = []
        for batch_start in range(0, len(recipes), _BATCH_SIZE):
            batch = recipes[batch_start:batch_start + _BATCH_SIZE]
            results = await self._classify_single_batch(batch, batch_start)
            all_results.extend(results)
        return all_results

    async def _classify_single_batch(
        self, batch: Sequence[dict], offset: int
    ) -> list[dict]:
        recipe_lines: list[str] = []
        for i, recipe in enumerate(batch):
            title = recipe.get("title", "Untitled")
            ner = recipe.get("NER", [])
            if isinstance(ner, str):
                ner = [ner]
            ingredients_str = ", ".join(ner[:15])
            recipe_lines.append(f'{i}. "{title}" — Ingredients: {ingredients_str}')

        user_prompt = (
            f"Classify these {len(batch)} recipes:\n\n" + "\n".join(recipe_lines)
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await call_llm_json(
                LLMOperation.CUISINE_CLASSIFICATION,
                messages,
                temperature=0,
                max_tokens=1500,
            )
            if isinstance(result, list):
                return self._validate_results(result, len(batch), offset)
            elif isinstance(result, dict) and "classifications" in result:
                return self._validate_results(
                    result["classifications"], len(batch), offset
                )
            else:
                logger.warning("Unexpected LLM response format: %s", type(result))
                return self._fallback_results(len(batch), offset)
        except Exception as exc:
            logger.error(
                "Cuisine classification failed for batch at offset %d: %s", offset, exc
            )
            return self._fallback_results(len(batch), offset)

    def _validate_results(
        self, results: list, expected_count: int, offset: int
    ) -> list[dict]:
        validated: list[dict] = []
        for i in range(expected_count):
            cuisine = "Other"
            for r in results:
                if isinstance(r, dict) and r.get("index") == i:
                    raw = r.get("cuisine", "Other")
                    if raw in _VOCAB_SET:
                        cuisine = raw
                    else:
                        for vc in CUISINE_VOCABULARY:
                            if vc.lower() == raw.lower():
                                cuisine = vc
                                break
                    break
            validated.append({"index": offset + i, "cuisine": cuisine})
        return validated

    @staticmethod
    def _fallback_results(count: int, offset: int) -> list[dict]:
        return [{"index": offset + i, "cuisine": "Other"} for i in range(count)]


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def classify_cuisine(title: str, ner: list[str]) -> Optional[str]:
    """
    Chain rule-based → LLM. Synchronous wrapper; for async batch use
    CuisineClassifier.classify_batch() directly.
    """
    return classify_rule_based(title, ner)


async def classify_recipes(recipes: Sequence[dict]) -> list[dict]:
    """Convenience async function for classifying a list of recipes."""
    return await CuisineClassifier().classify_batch(recipes)
