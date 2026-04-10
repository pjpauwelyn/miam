"""
CuisineClassifier — two-pass rule-based cuisine classification with LLM fallback.

Pass 1: Title keyword matching (exact cuisine name or known dish name → immediate assign).
Pass 2: Ingredient scoring (weighted term lists per cuisine → highest score wins).
Fallback: Records with no confident match (score < MIN_SCORE_THRESHOLD and no title hit)
          are sent to Mistral Small in batches of 20, identical to the original LLM path.

Public API is unchanged:
    classifier = CuisineClassifier()
    results = await classifier.classify_batch(recipes)
    # [{"index": 0, "cuisine": "Italian"}, ...]
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Sequence

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.llm_router import LLMOperation, call_llm_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Controlled vocabulary (unchanged)
# ---------------------------------------------------------------------------

CUISINE_VOCABULARY: list[str] = [
    "Italian", "French", "Spanish", "Greek", "Moroccan",
    "Lebanese", "Turkish", "Indian", "Chinese", "Japanese",
    "Korean", "Thai", "Vietnamese", "Mexican", "Peruvian",
    "American", "British", "German", "Dutch", "Scandinavian",
    "Middle Eastern", "African", "Caribbean", "Fusion", "Other",
]

# Minimum ingredient score to assign a cuisine without a title hit.
# Below this threshold the record is sent to the LLM fallback.
MIN_SCORE_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Pass 1 — Title keyword map
# Maps lowercase title substrings / dish names to a CUISINE_VOCABULARY entry.
# Longer / more specific phrases are checked before shorter ones (see _match_title).
#
# SHADOWING RULE: whenever a short phrase X already maps to cuisine C, any compound
# dish that contains X but belongs to a different cuisine MUST be listed here as a
# longer entry so the length-descending sort picks it up first.
# Examples of guarded compounds:
#   "fried rice" → Chinese, so "kimchi fried rice", "thai fried rice",
#                  "pineapple fried rice" are listed explicitly.
#   "curry"      → Indian, so "thai green curry" / "thai red curry" are listed.
#   "miso"       → Japanese, "ramen" → Japanese, so "miso ramen" is redundant but
#                  explicit for clarity.
# ---------------------------------------------------------------------------

TITLE_KEYWORDS: dict[str, str] = {
    # — explicit cuisine labels —
    "italian": "Italian",
    "french": "French",
    "spanish": "Spanish",
    "greek": "Greek",
    "moroccan": "Moroccan",
    "lebanese": "Lebanese",
    "turkish": "Turkish",
    "indian": "Indian",
    "chinese": "Chinese",
    "japanese": "Japanese",
    "korean": "Korean",
    "thai": "Thai",
    "vietnamese": "Vietnamese",
    "mexican": "Mexican",
    "peruvian": "Peruvian",
    "american": "American",
    "british": "British",
    "german": "German",
    "dutch": "Dutch",
    "scandinavian": "Scandinavian",
    "nordic": "Scandinavian",
    "swedish": "Scandinavian",
    "norwegian": "Scandinavian",
    "danish": "Scandinavian",
    "finnish": "Scandinavian",
    "middle eastern": "Middle Eastern",
    "african": "African",
    "caribbean": "Caribbean",
    "jamaican": "Caribbean",
    "trinidadian": "Caribbean",
    "fusion": "Fusion",
    # — well-known dish names —
    # Italian
    "pizza": "Italian",
    "pasta": "Italian",
    "risotto": "Italian",
    "lasagna": "Italian",
    "lasagne": "Italian",
    "carbonara": "Italian",
    "bolognese": "Italian",
    "tiramisu": "Italian",
    "arancini": "Italian",
    "osso buco": "Italian",
    "gnocchi": "Italian",
    "pesto": "Italian",
    "bruschetta": "Italian",
    "focaccia": "Italian",
    "cannoli": "Italian",
    "panna cotta": "Italian",
    "saltimbocca": "Italian",
    "minestrone": "Italian",
    "ribollita": "Italian",
    "cacio e pepe": "Italian",
    "amatriciana": "Italian",
    "arrabiata": "Italian",
    "arrabbiata": "Italian",
    # French
    "quiche": "French",
    "crepe": "French",
    "crêpe": "French",
    "ratatouille": "French",
    "bouillabaisse": "French",
    "cassoulet": "French",
    "coq au vin": "French",
    "bœuf bourguignon": "French",
    "beef bourguignon": "French",
    "vichyssoise": "French",
    "crème brûlée": "French",
    "creme brulee": "French",
    "soufflé": "French",
    "souffle": "French",
    "tarte tatin": "French",
    "nicoise": "French",
    "niçoise": "French",
    "baguette": "French",
    "croissant": "French",
    "madeleine": "French",
    "eclair": "French",
    "éclair": "French",
    "profiterole": "French",
    "pot au feu": "French",
    "pot-au-feu": "French",
    # Compound guard: "french" already catches "french onion soup", but explicit is safer
    "french onion soup": "French",
    # Spanish
    "paella": "Spanish",
    "gazpacho": "Spanish",
    "tortilla espanola": "Spanish",
    "patatas bravas": "Spanish",
    "churros": "Spanish",
    "empanada": "Spanish",
    "croqueta": "Spanish",
    "croquetas": "Spanish",
    "albondigas": "Spanish",
    "fabada": "Spanish",
    "cocido": "Spanish",
    "pisto": "Spanish",
    "romesco": "Spanish",
    "catalan": "Spanish",
    "arroz con leche": "Spanish",
    # Greek
    "moussaka": "Greek",
    "spanakopita": "Greek",
    "tzatziki": "Greek",
    "souvlaki": "Greek",
    "gyros": "Greek",
    "gyro": "Greek",
    "baklava": "Greek",
    "dolmades": "Greek",
    "dolma": "Greek",
    "pastitsio": "Greek",
    "horiatiki": "Greek",
    "skordalia": "Greek",
    "galaktoboureko": "Greek",
    # Moroccan
    "tagine": "Moroccan",
    "tajine": "Moroccan",
    "chermoula": "Moroccan",
    "harira": "Moroccan",
    "bastilla": "Moroccan",
    "pastilla": "Moroccan",
    "ras el hanout": "Moroccan",
    "merguez": "Moroccan",
    # Lebanese
    "hummus": "Lebanese",
    "falafel": "Lebanese",
    "tabbouleh": "Lebanese",
    "fattoush": "Lebanese",
    "kibbeh": "Lebanese",
    "shawarma": "Lebanese",
    "labneh": "Lebanese",
    "manakish": "Lebanese",
    "mujadara": "Lebanese",
    # Turkish
    "kebab": "Turkish",
    "kofte": "Turkish",
    "köfte": "Turkish",
    "pide": "Turkish",
    "borek": "Turkish",
    "börek": "Turkish",
    "manti": "Turkish",
    "lahmacun": "Turkish",
    "iskender": "Turkish",
    "menemen": "Turkish",
    # Indian
    # Compound guard: "chicken tikka masala" listed explicitly (tikka masala already present)
    "chicken tikka masala": "Indian",
    "tikka masala": "Indian",
    "tikka": "Indian",
    "curry": "Indian",
    "biryani": "Indian",
    "dal": "Indian",
    "dahl": "Indian",
    "daal": "Indian",
    "samosa": "Indian",
    "naan": "Indian",
    "roti": "Indian",
    "chapati": "Indian",
    "paneer": "Indian",
    "korma": "Indian",
    "vindaloo": "Indian",
    "saag": "Indian",
    "palak": "Indian",
    "chana": "Indian",
    "aloo": "Indian",
    "gobi": "Indian",
    "masala": "Indian",
    "tandoori": "Indian",
    "raita": "Indian",
    "kheer": "Indian",
    "gulab jamun": "Indian",
    "halwa": "Indian",
    "paratha": "Indian",
    "dosa": "Indian",
    "idli": "Indian",
    "uttapam": "Indian",
    "rasam": "Indian",
    "sambar": "Indian",
    # Chinese
    "dim sum": "Chinese",
    "wonton": "Chinese",
    "dumpling": "Chinese",
    # Compound guard: "fried rice" → Chinese, but kimchi/thai/pineapple variants belong elsewhere
    "kimchi fried rice": "Korean",
    "thai fried rice": "Thai",
    "pineapple fried rice": "Thai",
    "fried rice": "Chinese",
    "chow mein": "Chinese",
    "lo mein": "Chinese",
    "kung pao": "Chinese",
    "mapo tofu": "Chinese",
    "peking duck": "Chinese",
    "peking": "Chinese",
    "char siu": "Chinese",
    "congee": "Chinese",
    "spring roll": "Chinese",
    "egg roll": "Chinese",
    "hot pot": "Chinese",
    "hotpot": "Chinese",
    "szechuan": "Chinese",
    "sichuan": "Chinese",
    "cantonese": "Chinese",
    "shanghainese": "Chinese",
    "hoisin": "Chinese",
    "bok choy": "Chinese",
    "baozi": "Chinese",
    "bao bun": "Chinese",
    # Japanese
    "sushi": "Japanese",
    "ramen": "Japanese",
    # Compound guard: "miso ramen" is unambiguous; listed explicitly for clarity
    "miso ramen": "Japanese",
    "udon": "Japanese",
    "soba": "Japanese",
    "tempura": "Japanese",
    "teriyaki": "Japanese",
    "yakitori": "Japanese",
    "miso": "Japanese",
    "tonkatsu": "Japanese",
    "katsu": "Japanese",
    "gyoza": "Japanese",
    "takoyaki": "Japanese",
    "okonomiyaki": "Japanese",
    "onigiri": "Japanese",
    "donburi": "Japanese",
    "sukiyaki": "Japanese",
    "shabu shabu": "Japanese",
    "dashi": "Japanese",
    "edamame": "Japanese",
    "matcha": "Japanese",
    "wagashi": "Japanese",
    # Compound guard: "japanese fried chicken" → Japanese (not Chinese via "fried")
    "japanese fried chicken": "Japanese",
    # Korean
    "bibimbap": "Korean",
    "kimchi": "Korean",
    "bulgogi": "Korean",
    "japchae": "Korean",
    "tteokbokki": "Korean",
    "galbi": "Korean",
    "sundubu": "Korean",
    "doenjang": "Korean",
    "gochujang": "Korean",
    "jjigae": "Korean",
    "kimbap": "Korean",
    "pajeon": "Korean",
    "samgyeopsal": "Korean",
    # Compound guard: "korean fried chicken" → Korean (not Chinese via "fried")
    "korean fried chicken": "Korean",
    # Thai
    "pad thai": "Thai",
    "pad see ew": "Thai",
    # Compound guard: "thai green/red curry" listed before bare "green/red curry" and "curry"
    "thai green curry": "Thai",
    "thai red curry": "Thai",
    "green curry": "Thai",
    "red curry": "Thai",
    "yellow curry": "Thai",
    "massaman": "Thai",
    "tom yum": "Thai",
    "tom kha": "Thai",
    "larb": "Thai",
    "som tam": "Thai",
    "papaya salad": "Thai",
    "pad krapao": "Thai",
    "khao pad": "Thai",
    "satay": "Thai",
    "mango sticky rice": "Thai",
    # Vietnamese
    "pho": "Vietnamese",
    "phở": "Vietnamese",
    "banh mi": "Vietnamese",
    "bánh mì": "Vietnamese",
    "bun bo hue": "Vietnamese",
    "goi cuon": "Vietnamese",
    "com tam": "Vietnamese",
    "bun cha": "Vietnamese",
    "cao lau": "Vietnamese",
    "mi quang": "Vietnamese",
    # Mexican
    "taco": "Mexican",
    "burrito": "Mexican",
    "enchilada": "Mexican",
    "quesadilla": "Mexican",
    "guacamole": "Mexican",
    "salsa": "Mexican",
    "tamale": "Mexican",
    "tamales": "Mexican",
    "mole": "Mexican",
    "pozole": "Mexican",
    "chilaquiles": "Mexican",
    "huevos rancheros": "Mexican",
    "carnitas": "Mexican",
    "ceviche": "Mexican",
    "chili": "Mexican",
    "fajita": "Mexican",
    "fajitas": "Mexican",
    "nacho": "Mexican",
    "nachos": "Mexican",
    "elote": "Mexican",
    "horchata": "Mexican",
    "churro": "Mexican",
    # Peruvian
    "lomo saltado": "Peruvian",
    "aji de gallina": "Peruvian",
    "causa": "Peruvian",
    "anticuchos": "Peruvian",
    "tiradito": "Peruvian",
    "cau cau": "Peruvian",
    # American
    "burger": "American",
    "hamburger": "American",
    "bbq": "American",
    "barbecue": "American",
    "mac and cheese": "American",
    "macaroni and cheese": "American",
    "cornbread": "American",
    "clam chowder": "American",
    "new england": "American",
    "buffalo wing": "American",
    "buffalo chicken": "American",
    "thanksgiving": "American",
    "meatloaf": "American",
    "pot roast": "American",
    "biscuits and gravy": "American",
    "pancake": "American",
    "waffle": "American",
    "brownie": "American",
    "cheesecake": "American",
    "pecan pie": "American",
    "apple pie": "American",
    "pumpkin pie": "American",
    "southern fried": "American",
    "cajun": "American",
    "creole": "American",
    "tex-mex": "Fusion",
    # British
    "fish and chips": "British",
    "shepherd's pie": "British",
    "shepherds pie": "British",
    "cottage pie": "British",
    "bangers and mash": "British",
    "toad in the hole": "British",
    "yorkshire pudding": "British",
    "beef wellington": "British",
    "scone": "British",
    "crumpet": "British",
    "victoria sponge": "British",
    "eton mess": "British",
    "sticky toffee pudding": "British",
    "bread and butter pudding": "British",
    "cornish pasty": "British",
    "welsh rarebit": "British",
    "scotch egg": "British",
    "haggis": "British",
    "colcannon": "British",
    "irish stew": "British",
    # German
    "sauerkraut": "German",
    "schnitzel": "German",
    "bratwurst": "German",
    "pretzel": "German",
    "strudel": "German",
    "kartoffelsalat": "German",
    "sauerbraten": "German",
    "rouladen": "German",
    "zwiebelkuchen": "German",
    "flammkuchen": "German",
    "spatzle": "German",
    "spätzle": "German",
    "lebkuchen": "German",
    "black forest": "German",
    # Caribbean
    "jerk chicken": "Caribbean",
    "jerk": "Caribbean",
    "plantain": "Caribbean",
    "rice and peas": "Caribbean",
    "ackee": "Caribbean",
    "doubles": "Caribbean",
    "callaloo": "Caribbean",
    "escovitch": "Caribbean",
    "pepperpot": "Caribbean",
    # African
    "jollof": "African",
    "egusi": "African",
    "injera": "African",
    "doro wat": "African",
    "suya": "African",
    "fufu": "African",
    "bobotie": "African",
    "peri peri": "African",
    "piri piri": "African",
    "bunny chow": "African",
    # Middle Eastern
    "mansaf": "Middle Eastern",
    "maqluba": "Middle Eastern",
    "musakhan": "Middle Eastern",
    "knafeh": "Middle Eastern",
    "kunafa": "Middle Eastern",
    "muhammar": "Middle Eastern",
    "kabsa": "Middle Eastern",
    "harees": "Middle Eastern",
    # Scandinavian
    "gravlax": "Scandinavian",
    "gravadlax": "Scandinavian",
    "smorgasbord": "Scandinavian",
    "smörgåsbord": "Scandinavian",
    "lefse": "Scandinavian",
    "lutefisk": "Scandinavian",
    "meatball": "Scandinavian",
    "kladdkaka": "Scandinavian",
    "kanelbulle": "Scandinavian",
    "cinnamon bun": "Scandinavian",
    "cardamom bun": "Scandinavian",
}

# ---------------------------------------------------------------------------
# Pass 2 — Ingredient scoring
# Each cuisine maps to a set of weighted (term, score) pairs.
# Score 2 = strong signal (unique to one cuisine)
# Score 1 = moderate signal (shared across a few cuisines)
# ---------------------------------------------------------------------------

INGREDIENT_SCORES: dict[str, list[tuple[str, int]]] = {
    "Italian": [
        ("parmesan", 2), ("parmigiano", 2), ("pecorino", 2), ("pancetta", 2),
        ("prosciutto", 2), ("mozzarella", 2), ("ricotta", 2), ("mascarpone", 2),
        ("basil", 1), ("oregano", 1), ("pasta", 2), ("spaghetti", 2),
        ("penne", 2), ("fettuccine", 2), ("rigatoni", 2), ("lasagne", 2),
        ("lasagna", 2), ("gnocchi", 2), ("polenta", 2), ("arborio", 2),
        ("risotto", 2), ("olive oil", 1), ("tomato", 1), ("garlic", 1),
        ("capers", 1), ("anchov", 1), ("balsamic", 2), ("focaccia", 2),
        ("ciabatta", 2), ("cannellini", 2), ("borlotti", 2),
    ],
    "French": [
        ("dijon", 2), ("dijon mustard", 2), ("tarragon", 2), ("herbes de provence", 2),
        ("gruyère", 2), ("gruyere", 2), ("brie", 2), ("camembert", 2),
        ("crème fraîche", 2), ("creme fraiche", 2), ("double cream", 1),
        ("shallot", 2), ("leek", 1), ("lardons", 2), ("cognac", 2),
        ("brandy", 1), ("white wine", 1), ("béchamel", 2), ("bechamel", 2),
        ("roux", 2), ("puff pastry", 1), ("french bread", 2), ("baguette", 2),
        ("comté", 2), ("roquefort", 2), ("lavender", 1), ("thyme", 1),
    ],
    "Spanish": [
        ("smoked paprika", 2), ("chorizo", 2), ("saffron", 2), ("manchego", 2),
        ("pimentón", 2), ("pimenton", 2), ("serrano", 2), ("iberico", 2),
        ("paella", 2), ("bomba rice", 2), ("sherry", 2), ("romesco", 2),
        ("calasparra", 2), ("sofrito", 1), ("piquillo", 2), ("albariño", 2),
    ],
    "Greek": [
        ("feta", 2), ("kalamata", 2), ("kalamata olive", 2), ("pita", 1),
        ("tzatziki", 2), ("oregano", 1), ("lamb", 1), ("phyllo", 2),
        ("filo", 2), ("halloumi", 2), ("dill", 1), ("lemon", 1),
        ("chickpea", 1), ("spinach", 1), ("ouzo", 2), ("tahini", 1),
    ],
    "Moroccan": [
        ("ras el hanout", 2), ("preserved lemon", 2), ("harissa", 2),
        ("couscous", 2), ("merguez", 2), ("argan", 2), ("chermoula", 2),
        ("cumin", 1), ("coriander", 1), ("cinnamon", 1), ("ginger", 1),
        ("dried apricot", 1), ("prune", 1), ("honey", 1), ("almond", 1),
        ("saffron", 1), ("chickpea", 1), ("lamb", 1),
    ],
    "Lebanese": [
        ("za'atar", 2), ("zaatar", 2), ("sumac", 2), ("pomegranate molasses", 2),
        ("tahini", 2), ("bulgur", 2), ("freekeh", 2), ("labneh", 2),
        ("flatbread", 1), ("pine nut", 2), ("allspice", 1), ("rose water", 1),
        ("parsley", 1), ("lemon juice", 1), ("eggplant", 1), ("aubergine", 1),
        ("chickpea", 1), ("lamb", 1), ("halloumi", 1),
    ],
    "Turkish": [
        ("turkish pepper", 2), ("urfa biber", 2), ("isot", 2), ("pul biber", 2),
        ("pomegranate molasses", 1), ("sumac", 1), ("bulgur", 1),
        ("lamb", 1), ("eggplant", 1), ("aubergine", 1), ("yogurt", 1),
        ("mint", 1), ("flatbread", 1), ("pistachios", 1), ("rose water", 1),
        ("phyllo", 1), ("filo", 1),
    ],
    "Indian": [
        ("garam masala", 2), ("turmeric", 2), ("cumin", 1), ("coriander", 1),
        ("cardamom", 2), ("fenugreek", 2), ("mustard seed", 2), ("curry leaf", 2),
        ("curry powder", 2), ("tandoori", 2), ("paneer", 2), ("ghee", 2),
        ("chana", 2), ("masoor", 2), ("urad dal", 2), ("lentil", 1),
        ("basmati", 2), ("naan", 2), ("roti", 1), ("chapati", 2),
        ("tamarind", 1), ("coconut milk", 1), ("asafoetida", 2), ("hing", 2),
        ("chili", 1), ("ginger", 1), ("garlic", 1),
    ],
    "Chinese": [
        ("soy sauce", 2), ("oyster sauce", 2), ("hoisin", 2), ("sesame oil", 2),
        ("five spice", 2), ("star anise", 2), ("shaoxing", 2), ("rice wine", 1),
        ("bok choy", 2), ("pak choi", 2), ("chinese cabbage", 2),
        ("water chestnut", 2), ("bamboo shoot", 2), ("shiitake", 1),
        ("tofu", 1), ("spring onion", 1), ("scallion", 1), ("ginger", 1),
        ("rice vinegar", 1), ("wonton", 2), ("rice noodle", 1),
        ("chinese five", 2), ("black bean sauce", 2), ("doubanjiang", 2),
    ],
    "Japanese": [
        ("miso", 2), ("mirin", 2), ("dashi", 2), ("kombu", 2), ("bonito", 2),
        ("katsuobushi", 2), ("nori", 2), ("wakame", 2), ("ponzu", 2),
        ("sake", 1), ("tofu", 1), ("edamame", 2), ("matcha", 2),
        ("panko", 2), ("soba", 2), ("udon", 2), ("ramen", 2),
        ("rice vinegar", 1), ("sesame", 1), ("shiso", 2), ("wasabi", 2),
        ("teriyaki", 2), ("tempura", 2), ("japanese", 2),
    ],
    "Korean": [
        ("gochujang", 2), ("gochugaru", 2), ("doenjang", 2), ("kimchi", 2),
        ("sesame oil", 1), ("perilla", 2), ("bap", 1), ("soju", 2),
        ("rice cake", 1), ("tteok", 2), ("galbi", 2), ("bulgogi", 2),
        ("fish sauce", 1), ("scallion", 1), ("garlic", 1), ("ginger", 1),
        ("korean chili", 2), ("napa cabbage", 1), ("daikon", 1),
    ],
    "Thai": [
        ("fish sauce", 2), ("thai basil", 2), ("kaffir lime", 2), ("lemongrass", 2),
        ("galangal", 2), ("coconut milk", 2), ("thai chili", 2), ("bird's eye", 2),
        ("birds eye chili", 2), ("palm sugar", 2), ("thai curry paste", 2),
        ("red curry paste", 2), ("green curry paste", 2), ("nam pla", 2),
        ("jasmine rice", 2), ("pad thai", 2), ("tamarind", 1),
        ("shrimp paste", 1), ("oyster sauce", 1),
    ],
    "Vietnamese": [
        ("fish sauce", 1), ("rice paper", 2), ("rice noodle", 1),
        ("vietnamese mint", 2), ("perilla", 1), ("lemongrass", 1),
        ("bean sprout", 2), ("hoisin", 1), ("star anise", 1),
        ("cinnamon", 1), ("clove", 1), ("bun", 1),
        ("nuoc cham", 2), ("nuoc mam", 2), ("banh mi", 2),
        ("pho", 2), ("fresh herb", 1),
    ],
    "Mexican": [
        ("chipotle", 2), ("ancho", 2), ("guajillo", 2), ("pasilla", 2),
        ("epazote", 2), ("tomatillo", 2), ("corn tortilla", 2), ("masa", 2),
        ("achiote", 2), ("black bean", 1), ("pinto bean", 1), ("avocado", 1),
        ("jalapeno", 2), ("jalapeño", 2), ("serrano pepper", 2),
        ("cilantro", 2), ("lime", 1), ("cotija", 2), ("queso fresco", 2),
        ("mexican oregano", 2), ("cumin", 1), ("chili powder", 1),
    ],
    "Peruvian": [
        ("aji amarillo", 2), ("aji panca", 2), ("rocoto", 2), ("huacatay", 2),
        ("chicha", 2), ("quinoa", 1), ("purple corn", 2), ("pisco", 2),
        ("cancha", 2), ("choclo", 2), ("causa", 2), ("uchucuta", 2),
    ],
    "American": [
        ("buttermilk", 2), ("all-purpose flour", 1), ("baking powder", 1),
        ("maple syrup", 2), ("bourbon", 2), ("cheddar", 1),
        ("cream cheese", 1), ("sour cream", 1), ("corn", 1),
        ("cornmeal", 2), ("molasses", 2), ("liquid smoke", 2),
        ("ranch", 2), ("american mustard", 2), ("yellow mustard", 2),
        ("hot sauce", 1), ("worcestershire", 1), ("bacon", 1),
    ],
    "British": [
        ("double cream", 2), ("clotted cream", 2), ("stilton", 2),
        ("cheddar", 1), ("worcestershire sauce", 2), ("marmite", 2),
        ("golden syrup", 2), ("treacle", 2), ("suet", 2), ("lard", 1),
        ("swede", 2), ("parsnip", 1), ("brussels sprout", 1),
        ("black pudding", 2), ("white pudding", 2), ("mushy peas", 2),
        ("hp sauce", 2), ("malt vinegar", 2), ("english mustard", 2),
        ("marmalade", 2), ("custard powder", 2), ("self-raising flour", 2),
    ],
    "German": [
        ("sauerkraut", 2), ("juniper berry", 2), ("caraway", 2),
        ("bratwurst", 2), ("weisswurst", 2), ("knockwurst", 2),
        ("rye flour", 2), ("rye bread", 2), ("pumpernickel", 2),
        ("quark", 2), ("lebkuchen", 2), ("marzipan", 1),
        ("white asparagus", 2), ("speck", 1), ("mustard", 1),
        ("lager", 1), ("beer", 1),
    ],
    "Dutch": [
        ("gouda", 2), ("edam", 2), ("dutch", 2), ("stroopwafel", 2),
        ("speculaas", 2), ("hagelslag", 2), ("dutch oven", 1),
        ("hutspot", 2), ("stamppot", 2), ("erwtensoep", 2),
        ("jenever", 2), ("genever", 2),
    ],
    "Scandinavian": [
        ("dill", 2), ("lingonberry", 2), ("cloudberry", 2),
        ("cardamom", 1), ("gravlax", 2), ("gravadlax", 2),
        ("crispbread", 2), ("knackebrod", 2), ("knäckebröd", 2),
        ("aquavit", 2), ("lutefisk", 2), ("lefse", 2),
        ("mustard", 1), ("herring", 2), ("crayfish", 1),
        ("beetroot", 1), ("horseradish", 1), ("rye", 1),
    ],
    "Middle Eastern": [
        ("sumac", 2), ("za'atar", 2), ("zaatar", 2), ("harissa", 1),
        ("tahini", 1), ("rose water", 1), ("orange blossom", 2),
        ("pomegranate", 1), ("baharat", 2), ("7 spice", 2),
        ("seven spice", 2), ("lamb", 1), ("pine nut", 1),
        ("flatbread", 1), ("dried lime", 2), ("loomi", 2),
        ("cardamom", 1), ("saffron", 1), ("eggplant", 1),
    ],
    "African": [
        ("berbere", 2), ("tej", 2), ("injera", 2), ("niter kibbeh", 2),
        ("egusi", 2), ("ogiri", 2), ("crayfish powder", 2),
        ("suya spice", 2), ("peri peri", 2), ("piri piri", 2),
        ("palm oil", 2), ("plantain", 1), ("cassava", 2),
        ("yam", 1), ("fufu", 2), ("dawadawa", 2),
    ],
    "Caribbean": [
        ("scotch bonnet", 2), ("allspice", 2), ("jerk seasoning", 2),
        ("coconut milk", 1), ("plantain", 2), ("ackee", 2),
        ("saltfish", 2), ("thyme", 1), ("rum", 2), ("molasses", 1),
        ("callaloo", 2), ("breadfruit", 2), ("cassava", 1),
        ("pigeon pea", 2), ("kidney bean", 1), ("habanero", 1),
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase + collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _match_title(title: str) -> str | None:
    """
    Scan the recipe title for known cuisine keywords / dish names.
    Returns a CUISINE_VOCABULARY entry or None.
    Longer phrases checked first to avoid partial false matches.
    """
    t = _norm(title)
    # Sort by length descending so multi-word phrases win
    for phrase in sorted(TITLE_KEYWORDS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(phrase) + r"\b", t):
            return TITLE_KEYWORDS[phrase]
    return None


def _score_ingredients(ner: list[str]) -> tuple[str | None, int]:
    """
    Score each cuisine against the ingredient list.
    Returns (best_cuisine, score) or (None, 0) if no cuisine clears MIN_SCORE_THRESHOLD.
    """
    normalised = [_norm(n) for n in ner if n.strip()]
    scores: dict[str, int] = {}

    for cuisine, terms in INGREDIENT_SCORES.items():
        total = 0
        for term, weight in terms:
            for ing in normalised:
                if re.search(r"\b" + re.escape(term) + r"\b", ing):
                    total += weight
                    break  # count each term once per recipe
        if total > 0:
            scores[cuisine] = total

    if not scores:
        return None, 0

    best_cuisine = max(scores, key=lambda c: scores[c])
    best_score = scores[best_cuisine]

    # Tie-breaking: if top two cuisines within 1 point, return None (ambiguous)
    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) >= 2 and (sorted_scores[0] - sorted_scores[1]) < 2:
        # Ambiguous — let LLM fallback decide
        return None, best_score

    return (best_cuisine if best_score >= MIN_SCORE_THRESHOLD else None), best_score


# ---------------------------------------------------------------------------
# Rule-based classification (synchronous)
# ---------------------------------------------------------------------------

def classify_rule_based(title: str, ner: list[str]) -> str | None:
    """
    Classify a single recipe using title keywords + ingredient scoring.
    Returns a CUISINE_VOCABULARY string, or None if unresolved (needs LLM).
    """
    # Pass 1: title
    cuisine = _match_title(title)
    if cuisine:
        return cuisine

    # Pass 2: ingredient scoring
    cuisine, _score = _score_ingredients(ner)
    return cuisine  # None = ambiguous, caller routes to LLM


# ---------------------------------------------------------------------------
# LLM fallback (unchanged from original, async)
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
- Consider ingredient patterns: e.g. soy sauce + ginger + rice = likely East Asian; cumin + coriander + chickpea = likely Middle Eastern/Indian.
- If the title explicitly names a cuisine (e.g. "Thai Green Curry"), honour it.
- Return ONLY the JSON array, no markdown, no explanation."""


async def _llm_classify_batch(batch: list[dict], offset: int) -> list[dict]:
    """Send a batch of unresolved recipes to the LLM. Same logic as original."""
    recipe_lines: list[str] = []
    for i, recipe in enumerate(batch):
        title = recipe.get("title", "Untitled")
        ner = recipe.get("NER", [])
        if isinstance(ner, str):
            ner = [ner]
        ingredients_str = ", ".join(ner[:15])
        recipe_lines.append(f'{i}. "{title}" — Ingredients: {ingredients_str}')

    user_prompt = (
        f"Classify these {len(batch)} recipes:\n\n"
        + "\n".join(recipe_lines)
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
        raw = result if isinstance(result, list) else result.get("classifications", [])
        validated: list[dict] = []
        for i in range(len(batch)):
            cuisine = "Other"
            for r in raw:
                if isinstance(r, dict) and r.get("index") == i:
                    c = r.get("cuisine", "Other")
                    cuisine = c if c in CUISINE_VOCABULARY else "Other"
                    break
            validated.append({"index": offset + i, "cuisine": cuisine})
        return validated
    except Exception as exc:
        logger.error("LLM fallback failed at offset %d: %s", offset, exc)
        return [{"index": offset + i, "cuisine": "Other"} for i in range(len(batch))]


# ---------------------------------------------------------------------------
# Public API — CuisineClassifier (interface unchanged)
# ---------------------------------------------------------------------------

class CuisineClassifier:
    """
    Two-pass rule-based cuisine classifier with LLM fallback for ambiguous records.

    Pass 1: Title keyword matching.
    Pass 2: Ingredient scoring (weighted term sets per cuisine).
    Fallback: Unresolved records (≈ 10–15%) sent to Mistral Small in batches of 20.

    Usage:
        classifier = CuisineClassifier()
        results = await classifier.classify_batch(recipes)
        # [{"index": 0, "cuisine": "Italian"}, ...]
    """

    async def classify_batch(
        self,
        recipes: Sequence[dict],
    ) -> list[dict]:
        """
        Classify a list of recipes. Public API unchanged.

        Args:
            recipes: List of dicts with "title" and "NER" (ingredient names) keys.

        Returns:
            List of {"index": int, "cuisine": str} in input order.
        """
        results: dict[int, str] = {}
        unresolved: list[tuple[int, dict]] = []  # (original_index, recipe)

        # — Pass 1 + 2: rule-based —
        for i, recipe in enumerate(recipes):
            title = recipe.get("title", "")
            ner = recipe.get("NER", [])
            if isinstance(ner, str):
                ner = [ner]
            cuisine = classify_rule_based(title, ner)
            if cuisine:
                results[i] = cuisine
            else:
                unresolved.append((i, recipe))

        rule_resolved = len(results)
        logger.info(
            "Rule-based: %d/%d resolved (%.0f%%). LLM fallback: %d records.",
            rule_resolved, len(recipes),
            100 * rule_resolved / max(len(recipes), 1),
            len(unresolved),
        )

        # — LLM fallback for unresolved —
        if unresolved:
            # Re-index for LLM batching (0-based within each batch)
            llm_recipes = [r for _, r in unresolved]
            for batch_start in range(0, len(llm_recipes), _BATCH_SIZE):
                batch = llm_recipes[batch_start:batch_start + _BATCH_SIZE]
                batch_results = await _llm_classify_batch(batch, batch_start)
                for item in batch_results:
                    local_idx = item["index"]
                    original_idx = unresolved[local_idx][0]
                    results[original_idx] = item["cuisine"]

        # — Return in original order —
        return [{"index": i, "cuisine": results.get(i, "Other")} for i in range(len(recipes))]


async def classify_recipes(recipes: Sequence[dict]) -> list[dict]:
    """Convenience function: classify a list of recipes."""
    classifier = CuisineClassifier()
    return await classifier.classify_batch(recipes)
