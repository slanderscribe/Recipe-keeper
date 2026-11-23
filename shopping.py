"""Turn recipe ingredient lines into shopping items: one item per ingredient, with the amount
rounded up to the whole package you would buy.

The package sizes are typical US store sizes and are approximate. Edit PACKAGES to match what
your store sells.
"""
import math
import re
from fractions import Fraction

# Grams per cup for dry goods (liquids default to 1 g per ml).
# packs: (size, label). For "each" items, size is a count.
PACKAGES = {
    "flour": {"per_cup": 125, "packs": [(454, "1 lb bag"), (907, "2 lb bag"), (1814, "4 lb bag")]},
    "sugar": {"per_cup": 200, "packs": [(907, "2 lb bag"), (1814, "4 lb bag")]},
    "brown sugar": {"per_cup": 200, "packs": [(454, "1 lb bag"), (907, "2 lb bag")]},
    "butter": {"per_cup": 227, "stick_g": 113, "packs": [(454, "1 lb (4 sticks)")]},
    "egg": {"each": True, "each_g": 50, "packs": [(12, "dozen")]},
    "milk": {"per_cup": 240, "packs": [(946, "quart"), (1893, "half gallon")]},
    "vegetable oil": {"per_cup": 218, "packs": [(946, "32 oz bottle"), (1419, "48 oz bottle")]},
    "honey": {"per_cup": 340, "packs": [(340, "12 oz bottle"), (680, "24 oz bottle")]},
    "vanilla extract": {"packs": [(59, "2 fl oz bottle"), (118, "4 fl oz bottle")]},
    "salt": {"per_cup": 288, "packs": [(737, "26 oz box")]},
    "baking soda": {"per_cup": 220, "packs": [(454, "1 lb box")]},
    "cinnamon": {"per_cup": 130, "packs": [(57, "2 oz jar")]},
    "rolled oats": {"per_cup": 90, "packs": [(510, "18 oz canister"), (1190, "42 oz canister")]},
    "wheat germ": {"per_cup": 115, "packs": [(340, "12 oz jar")]},
    "wheat bran": {"per_cup": 60, "packs": [(340, "12 oz bag")]},
    "coconut": {"per_cup": 85, "packs": [(340, "12 oz bag")]},
    "chocolate chips": {"per_cup": 170, "packs": [(340, "12 oz bag")]},
    "cornstarch": {"per_cup": 120, "packs": [(340, "12 oz box")]},
    "confectioners sugar": {"per_cup": 120, "packs": [(454, "1 lb bag"), (907, "2 lb bag")]},
    "baking powder": {"per_cup": 192, "packs": [(227, "8 oz can"), (454, "16 oz can")]},
    "buttermilk": {"packs": [(946, "quart"), (1893, "half gallon")]},
    "cream cheese": {"packs": [(227, "8 oz package"), (454, "16 oz (2 packages)")]},
    "sour cream": {"packs": [(454, "16 oz tub")]},
    "banana": {"each": True, "each_g": 118, "packs": [(5, "bunch (about 5)")]},
    "garlic": {"each": True, "each_g": 3, "packs": [(10, "head (about 10 cloves)")]},
    "lemon": {"each": True, "packs": [(1, "lemon")]},
}

# Other names for the same thing, so "all-purpose flour" and "flour" share one item.
SYNONYMS = [
    (r"^(all[- ]purpose |ap |plain |white )?flour$", "flour"),
    (r"^(granulated |white |caster )?sugar$", "sugar"),
    (r"^(light |dark |packed |firmly packed )?(brown|br\.?) sugar$", "brown sugar"),
    (r"^(unsalted |salted )?butter$", "butter"),
    (r"^(large |extra[- ]large |medium |small )?eggs?$", "egg"),
    (r"^(whole |2% |skim )?milk$", "milk"),
    (r"^(vegetable |canola |light )?oil$", "vegetable oil"),
    (r"^(pure )?vanilla( extract)?$", "vanilla extract"),
    (r"^(table |kosher |fine sea )?salt$", "salt"),
    (r"^(baking soda|bicarbonate of soda)$", "baking soda"),
    (r"^(ground )?cinnamon$", "cinnamon"),
    (r"^(old[- ]fashioned |rolled )?oats$", "rolled oats"),
    (r"^(rolled oats)$", "rolled oats"),
    (r"^wheat germ$", "wheat germ"),
    (r"^(wheat )?bran$", "wheat bran"),
    (r"^(shredded |sweetened |unsweetened )?coconut$", "coconut"),
    (r"^(semi[- ]sweet |mini )?chocolate chips?$", "chocolate chips"),
    (r"^(corn ?starch)$", "cornstarch"),
    (r"^honey$", "honey"),
    (r"^(confectioners?|powdered|icing|10x) sugar$", "confectioners sugar"),
    (r"^baking powder$", "baking powder"),
    (r"^(full[- ]fat |brick |block |regular )*cream cheese$", "cream cheese"),
    (r"^(sour cream)$", "sour cream"),
    (r"^buttermilk$", "buttermilk"),
]

# Words that describe an ingredient but are not part of what you buy.
DESCRIPTORS = [
    "large", "medium", "small", "extra large", "fresh", "freshly", "chopped", "minced", "diced",
    "sliced", "sifted", "softened", "melted", "room temperature", "cold", "divided", "packed",
    "finely", "coarsely", "beaten", "optional", "to taste", "or as needed", "as needed", "at room temperature",
    "heaping", "scant", "generous", "level", "full", "about", "ripe", "whole", "plain", "softened",
    "stiff", "warm", "lukewarm", "thawed", "drained", "rinsed", "peeled", "grated", "shredded",
    "mashed", "full fat", "brick", "block", "amount", "pinch of", "handful",
]
FILLER_WORDS = {"a", "an", "and", "or", "of", "about", "some", "few", "heaping", "scant", "generous", "level"}
UNCOUNTABLE_SINGULAR = {"molasses", "grits", "oats", "greens", "series", "news"}

UNIT_MAP = {
    # volume, in ml
    "cup": ("ml", 237), "cups": ("ml", 237), "c": ("ml", 237),
    "tbsp": ("ml", 14.8), "tbsps": ("ml", 14.8), "tablespoon": ("ml", 14.8), "tablespoons": ("ml", 14.8),
    "tsp": ("ml", 4.93), "tsps": ("ml", 4.93), "teaspoon": ("ml", 4.93), "teaspoons": ("ml", 4.93),
    "fl oz": ("ml", 29.57), "floz": ("ml", 29.57),
    "ml": ("ml", 1), "l": ("ml", 1000), "liter": ("ml", 1000), "liters": ("ml", 1000),
    "litre": ("ml", 1000), "litres": ("ml", 1000),
    # weight, in grams
    "oz": ("g", 28.35), "ounce": ("g", 28.35), "ounces": ("g", 28.35),
    "lb": ("g", 453.6), "lbs": ("g", 453.6), "pound": ("g", 453.6), "pounds": ("g", 453.6),
    "g": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "kg": ("g", 1000),
    # butter sticks use the stick weight from PACKAGES
    "stick": ("stick", 1), "sticks": ("stick", 1),
}
# Count words with no weight or volume: kept as the unit, but not converted.
COUNT_UNITS = {"can": "can", "cans": "can", "clove": "clove", "cloves": "clove", "pinch": "pinch",
               "pinches": "pinch", "dash": "dash", "package": "package", "packages": "package",
               "pkg": "package", "pkgs": "package", "bag": "bag", "bags": "bag", "jar": "jar", "jars": "jar"}
# Upper-case or dotted abbreviations are matched exactly, because "T" (tablespoon) and "t" (teaspoon) differ.
EXACT_UNITS = {"T": "tbsp", "T.": "tbsp", "t": "tsp", "t.": "tsp", "c.": "cup", "c": "cup",
               "tbs": "tbsp", "tbs.": "tbsp", "tsp.": "tsp", "tbsp.": "tbsp", "oz.": "oz", "lb.": "lb"}

FRACTION_CHARS = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8"}


def parse_quantity(text):
    """Read a leading amount like '2', '1/2', '1 1/2' or '½'. Returns (value, rest)."""
    for char, frac in FRACTION_CHARS.items():
        text = text.replace(char, frac if text.startswith(char) else f" {frac}")
    match = re.match(r"^\s*(\d+)\s*(?:and\s+)?(\d+/\d+)\b\s*", text, re.IGNORECASE)
    if match:
        value = float(int(match.group(1)) + Fraction(match.group(2)))
        return value, text[match.end():]
    match = re.match(r"^\s*(\d+/\d+|\d+(?:\.\d+)?)\s*", text)
    if match:
        part = match.group(1)
        value = float(Fraction(part)) if "/" in part else float(part)
        return value, text[match.end():]
    return None, text


def parse_unit(rest):
    """Read a unit at the start of the rest of the line. Returns (unit_name or None, rest)."""
    stripped = rest.lstrip()
    for token in sorted(list(EXACT_UNITS) + list(UNIT_MAP) + ["fl. oz", "fl oz"], key=len, reverse=True):
        pattern = r"^" + re.escape(token) + r"(?=\s|$|[,.(])"
        if re.match(pattern, stripped, re.IGNORECASE if token not in EXACT_UNITS else 0):
            if token in EXACT_UNITS:
                unit = EXACT_UNITS[token]
            else:
                unit = token.lower().replace("fl. oz", "fl oz")
            after = stripped[len(token):]
            after = re.sub(r"^\.", "", after)
            return unit, after
    for token in sorted(COUNT_UNITS, key=len, reverse=True):
        if re.match(r"^" + re.escape(token) + r"(?=\s|$)", stripped, re.IGNORECASE):
            return COUNT_UNITS[token], stripped[len(token):]
    return None, rest


# Words that describe how an ingredient is prepared, measured or sold. They are not part of the
# ingredient's identity, so they are dropped: "all purpose flour, spooned and leveled" -> "all purpose flour".
PREP_WORDS = {
    "spooned", "spoon", "leveled", "levelled", "level", "sifted", "unsifted", "packed", "firmly", "lightly",
    "loosely", "heaping", "heaped", "scant", "generous", "softened", "melted", "room", "temperature", "cold",
    "chilled", "frozen", "thawed", "warm", "cooled", "chopped", "minced", "diced", "cubed", "sliced",
    "grated", "shredded", "peeled", "rinsed", "drained", "toasted", "crushed", "beaten", "whisked",
    "divided", "optional", "fresh", "freshly", "large", "medium", "small", "extra", "jumbo", "boneless",
    "skinless", "ripe", "mashed", "light", "dark", "about", "approximately",
    "some", "more", "needed", "taste", "favorite", "good", "quality", "store", "bought", "homemade",
    "softened", "lukewarm", "stiff", "plain", "regular", "full", "fat", "brick", "block", "amount",
    "pinch", "handful", "sprig", "sprigs", "splash", "dash",
}
STOP_WORDS = {"a", "an", "the", "of", "and", "or", "with", "into", "in", "at", "from", "for", "to", "plus",
              "such", "as", "like", "e", "g", "etc", "each", "per", "total", "or"}
# Words that start a modifier after the ingredient name ("confectioners sugar if needed",
# "brown sugar tightly packed", "flour for dusting"). Everything from the first one on is dropped.
MODIFIER_STARTERS = {
    "if", "as", "for", "to", "with", "until", "when", "plus", "optional", "divided", "needed", "desired",
    "taste", "serving", "garnish", "dusting", "greasing", "more", "additional", "or", "at", "from", "into",
    "about", "such", "like", "per", "each", "etc", "room", "temperature", "cold", "warm", "softened",
    "melted", "chilled", "frozen", "thawed", "sifted", "chopped", "minced", "diced", "sliced", "beaten",
    "packed", "spooned", "leveled", "levelled", "drained", "rinsed", "peeled", "grated", "shredded",
    "mashed", "toasted", "crushed", "whisked", "cubed", "cooked", "uncooked", "dried",
}
# Ending-based modifiers ("tightly", "lightly", "finely", "dried") that are not ingredient names.
ED_WORDS_THAT_ARE_NAMES = {"bread", "hundred"}
LY_WORDS_THAT_ARE_NAMES = {"jelly", "belly", "curly", "family"}


def is_modifier_word(word):
    if word in MODIFIER_STARTERS:
        return True
    if len(word) >= 5 and word.endswith("ly") and word not in LY_WORDS_THAT_ARE_NAMES:
        return True
    if len(word) >= 5 and word.endswith("ed") and word not in ED_WORDS_THAT_ARE_NAMES:
        return True
    return False


def trim_modifiers(words):
    """Keep the ingredient name: cut the list at the first modifier that follows it."""
    for i, word in enumerate(words):
        if i > 0 and is_modifier_word(word):
            return words[:i]
    return words


def normalize_name(text):
    """Reduce an ingredient phrase to its identity: the thing you buy, with no measures or prep words."""
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\b(light|dark)\s*(or|/)\s*(light|dark)\b", " ", text, flags=re.IGNORECASE)
    text = re.split(r",|\s-\s|\s(?:or|to|for|plus|such as|like|about)\s", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.sub(r"^\s*of\s+", "", text.strip(), flags=re.IGNORECASE)
    lowered = text.lower().replace("-", " ").replace("’", "'").replace("'", "")
    lowered = re.sub(r"[^a-z\s]", " ", lowered)
    words = [w for w in trim_modifiers(lowered.split()) if w not in PREP_WORDS and w not in STOP_WORDS
             and w not in LABEL_WORDS and (w not in COUNT_WORDS or w in {"clove", "cloves"})]
    words = [singular(w) for w in words]
    words = list(dict.fromkeys(words))            # "bananas banana" -> "banana"
    return " ".join(words)


def singular(word):
    """Simple plural to singular: bananas -> banana, berries -> berry, cloves -> clove."""
    if word in UNCOUNTABLE_SINGULAR or len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


# A part of something rolls up into the whole: an egg yolk is part of an egg, a garlic clove is part
# of garlic, a vanilla bean is part of vanilla. Parts are added to the whole's count or amount.
PART_OF = {
    "egg yolk": "egg", "egg yolks": "egg", "egg white": "egg", "egg whites": "egg",
    "garlic clove": "garlic", "garlic cloves": "garlic", "garlic": "garlic",
    "vanilla bean": "vanilla extract", "vanilla beans": "vanilla extract", "vanilla pod": "vanilla extract",
}


def normalize_variant(name):
    """Lower case, hyphens and extra spaces removed, so 'All-purpose flour' and 'all purpose flour' match."""
    return " ".join(re.sub(r"[-']", " ", (name or "").lower()).split())


def item_key(name):
    # A named type (bread flour, active dry yeast, penne) is its own item. Checked first.
    variant = VARIANT_ALIASES.get(normalize_variant(name))
    if variant:
        return variant
    for pattern, key in SYNONYMS:
        if re.match(pattern, name):
            return PART_OF.get(key, key)
    return PART_OF.get(name, name)


PLURAL_DISPLAY = {"egg": "eggs"}  # items sold by the pack are shown in the plural


def display_name(key):
    key = PLURAL_DISPLAY.get(key, key)
    return key[:1].upper() + key[1:]


# Standard conversion table. Every unit is converted to grams (weight) or ml (volume) the same way.
WEIGHT_TO_G = {"g": 1, "gram": 1, "grams": 1, "gr": 1, "kg": 1000, "kgs": 1000,
               "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
               "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6}
VOLUME_TO_ML = {"cup": 236.6, "cups": 236.6, "c": 236.6,
                "tbsp": 14.8, "tbsps": 14.8, "tbs": 14.8, "tablespoon": 14.8, "tablespoons": 14.8,
                "tsp": 4.93, "tsps": 4.93, "teaspoon": 4.93, "teaspoons": 4.93,
                "fl oz": 29.57, "floz": 29.57,
                "ml": 1, "l": 1000, "liter": 1000, "liters": 1000, "litre": 1000, "litres": 1000}
STICK_WORDS = {"stick", "sticks"}
COUNT_WORDS = {"can", "cans", "clove", "cloves", "pinch", "pinches", "dash", "package", "packages",
               "pkg", "pkgs", "bag", "bags", "jar", "jars", "bunch", "bunches", "slice", "slices"}
# Unit words that are only labels: removed from the ingredient name.
LABEL_WORDS = {"grams", "gram", "g", "cups", "cup", "c", "tbsp", "tbsps", "tablespoons", "tablespoon",
               "tsp", "tsps", "teaspoons", "teaspoon", "oz", "ounces", "ounce", "lb", "lbs", "pounds",
               "pound", "ml", "plus", "and", "fl", "floz"}
NUMBER = r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"


def unit_kind(token):
    """Return ('weight'|'volume'|'stick'|'count', factor, label) for a unit token, or None."""
    raw = token.rstrip(".")
    if raw == "T":
        return ("volume", VOLUME_TO_ML["tbsp"], "tbsp")
    if raw == "t":
        return ("volume", VOLUME_TO_ML["tsp"], "tsp")
    if raw == "C":
        return ("volume", VOLUME_TO_ML["cup"], "cup")
    low = raw.lower()
    if low in WEIGHT_TO_G:
        return ("weight", WEIGHT_TO_G[low], low)
    if low in VOLUME_TO_ML:
        return ("volume", VOLUME_TO_ML[low], low)
    if low in STICK_WORDS:
        return ("stick", 1, low)
    if low in COUNT_WORDS:
        return ("count", 1, low)
    return None


def parse_value(text):
    text = text.strip()
    if " " in text:
        whole, frac = text.split(" ", 1)
        return float(int(whole) + Fraction(frac))
    if "/" in text:
        return float(Fraction(text))
    return float(text)


def parse_ingredient(line):
    """Read one ingredient line into what to buy: its name, its amount in grams or count, and what it says."""
    original = " ".join(line.split())
    text = original
    for char, frac in FRACTION_CHARS.items():
        text = text.replace(char, " " + frac)
    text = re.sub(r"(\d)\s+and\s+(\d+/\d+)", r"\1 \2", text, flags=re.IGNORECASE)
    text = re.sub(r"[()\[\]]", " ", text)

    measures = []  # (value, kind, factor, label)
    for match in re.finditer(NUMBER + r"\s*([A-Za-z]+\.?)(?=\s|$|[,.+/])", text):
        info = unit_kind(match.group(2))
        if info:
            kind, factor, label = info
            measures.append((parse_value(match.group(1)), kind, factor, label))
    spans_text = re.sub(NUMBER + r"\s*([A-Za-z]+\.?)(?=\s|$|[,.+/])",
                        lambda m: " " if unit_kind(m.group(2)) else m.group(0), text)
    bare = re.match(r"^\s*" + NUMBER + r"(?=\s|$|[,.])", spans_text)
    bare_value = parse_value(bare.group(1)) if bare else None
    if bare:
        spans_text = spans_text[bare.end():]

    weights = [m for m in measures if m[1] == "weight"]
    volumes = [m for m in measures if m[1] == "volume"]
    sticks = [m for m in measures if m[1] == "stick"]
    counts = [m for m in measures if m[1] == "count"]

    # "1/4 tsp cloves" is the spice, not a count of garlic cloves, so the word stays when a volume is given.
    keep_cloves = bool(volumes) and not weights
    name_words = [w for w in re.sub(r"[^A-Za-z\s\-\.']", " ", spans_text).replace("'", "").split()
                  if w.lower().strip(".") not in LABEL_WORDS
                  and (w.lower().strip(".") not in COUNT_WORDS
                       or (keep_cloves and w.lower().strip(".") in {"clove", "cloves"}))]
    name = normalize_name(" ".join(name_words))
    key = item_key(name) if name else ""
    spec = PACKAGES.get(key, {})

    grams = None
    count = None
    if weights:
        grams = sum(v * f for v, _, f, _ in weights)
    elif volumes:
        ml = sum(v * f for v, _, f, _ in volumes)
        if "per_cup" in spec:
            grams = ml * spec["per_cup"] / 236.6   # standard density for this ingredient
        elif spec and not spec.get("each"):
            grams = ml                              # liquids: 1 ml is about 1 g
    elif sticks and spec.get("stick_g"):
            grams = sum(v for v, _, _, _ in sticks) * spec["stick_g"]
    if spec.get("each"):
        if bare_value is not None and not volumes and not weights:
            count = bare_value
        if counts and not volumes and not weights:
            count = sum(v for v, _, _, _ in counts)
        if weights and not volumes and spec.get("each_g"):
            count = round(sum(v * f for v, _, f, _ in weights) / spec["each_g"], 1)
        grams = None
    amount_bits = [f"{format_amount(v)} {label}" for v, _, _, label in measures]
    if bare_value is not None and not measures:
        # A part keeps its own name in the amount, e.g. "2 egg yolks" rolls up into Egg.
        part = name if name in PART_OF else ""
        amount_bits = [" ".join(p for p in (format_amount(bare_value), part) if p)]
    if weights and volumes:
        amount_bits = [b for b, m in zip(amount_bits, measures) if m[1] != "volume"] or amount_bits
    return {
        "text": original,
        "key": key or name or original.lower(),
        "name": display_name(key or name or original),
        "grams": grams,
        "count": count,
        "amount": " + ".join(amount_bits),
        "known": is_known_key(key),
        "part": is_part_line(original, key, bool(measures) or bare_value is not None),
    }


def format_amount(value):
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def choose_package(key, grams, count):
    """Smallest package that covers the total; more of the largest one if needed."""
    spec = PACKAGES.get(key)
    if not spec:
        return None
    need = count if spec.get("each") else grams
    if need is None or need <= 0:
        return None
    packs = sorted(spec["packs"])
    for size, label in packs:
        if size >= need:
            return f"1 × {label}"
    size, label = packs[-1]
    return f"{math.ceil(need / size)} × {label}"


def purchase_text(key, lines):
    """What to buy for one item across all its recipe lines, or None if we can't work it out."""
    if not lines:
        return None
    if key not in PACKAGES:
        return None
    if any(l["grams"] is None and l["count"] is None for l in lines):
        return None
    grams = sum(l["grams"] or 0 for l in lines) or None
    count = sum(l["count"] or 0 for l in lines) or None
    return choose_package(key, grams, count)


PLURAL_UNITS = {"cup", "can", "clove", "stick", "package", "bag", "jar"}


def canonical_unit(unit):
    """'cups' and 'c.' are the same unit when adding amounts together."""
    unit = (unit or "").strip().lower().rstrip(".")
    if unit in ("c", "cup", "cups"):
        return "cup"
    if unit in ("tbsp", "tbsps", "tablespoon", "tablespoons", "t", "tbs"):
        return "tbsp"
    if unit in ("tsp", "tsps", "teaspoon", "teaspoons"):
        return "tsp"
    if unit in ("oz", "ounce", "ounces"):
        return "oz"
    if unit in ("lb", "lbs", "pound", "pounds"):
        return "lb"
    if unit in ("g", "gram", "grams"):
        return "g"
    if unit in ("can", "cans"):
        return "can"
    if unit in ("clove", "cloves"):
        return "clove"
    if unit in ("stick", "sticks"):
        return "stick"
    return unit


def combined_amounts(name, lines):
    """What the recipes call for. Same units are added together; different units are listed."""
    totals, order, loose = {}, [], []
    for line in lines:
        if "+" in (line["amount"] or "") or not line["amount"]:
            loose.append(line["amount"] or line["text"])
            continue
        value, rest = parse_quantity(line["amount"])
        if value is None:
            loose.append(line["text"])
            continue
        unit = canonical_unit(rest)
        if unit not in totals:
            totals[unit] = 0
            order.append(unit)
        totals[unit] += value
    groups = []
    for u in order:
        total = totals[u]
        label = u + "s" if total != 1 and u in PLURAL_UNITS else u
        groups.append(" ".join(p for p in (format_amount(total), label) if p))
    if len(order) == 1 and not loose:
        return groups[0]
    return " + ".join(groups + list(dict.fromkeys(loose)))


# ---------- strict names ----------
# The only names the shopping list accepts. Keys are singular, lower case, and match the names the
# parser produces. Anything else goes under "Check these" so a wrong name is never bought by mistake.
# To accept a new ingredient, add its singular name here.
KNOWN_INGREDIENTS = set(PACKAGES) | {
    # produce
    "onion", "carrot", "celery", "potato", "sweet potato", "ginger", "lime", "orange", "apple", "pear",
    "blueberry", "strawberry", "raspberry", "cranberry", "peach", "pineapple", "mango", "avocado",
    "tomato", "cucumber", "zucchini", "spinach", "lettuce", "broccoli", "cauliflower", "mushroom",
    "bell pepper", "jalapeno", "green onion", "shallot", "parsley", "cilantro", "basil", "mint",
    "rosemary", "thyme", "oregano", "dill", "pumpkin", "corn", "green bean", "pea", "cabbage",
    # dairy and eggs
    "heavy cream", "whipping cream", "half and half", "yogurt", "greek yogurt", "cheddar cheese",
    "parmesan cheese", "mozzarella cheese", "cheese", "ricotta cheese", "feta cheese", "ice cream",
    # pantry
    "bread crumb", "cornmeal", "yeast", "active dry yeast", "rice", "pasta", "spaghetti", "noodle",
    "pecan", "walnut", "almond", "peanut", "peanut butter", "sunflower seed", "sesame seed",
    "pumpkin seed", "pumpkin puree", "maple syrup", "corn syrup", "molasses", "cocoa powder",
    "chocolate", "white chocolate chip", "vanilla", "almond extract", "peppermint extract",
    "black pepper", "pepper", "paprika", "cumin", "chili powder", "nutmeg", "allspice", "ground ginger",
    "bay leaf", "garlic powder", "onion powder", "cayenne pepper", "soy sauce", "vinegar",
    "olive oil", "canola oil", "water", "broth", "chicken broth", "beef broth", "tomato sauce",
    "canned tomato", "tomato paste", "mayonnaise", "mustard", "ketchup", "salsa", "jam", "jelly",
    "marshmallow", "sprinkles", "graham cracker", "cookie", "pie crust", "tortilla", "bread", "oat",
    "cream of tartar", "espresso powder", "instant coffee", "tea", "coffee", "ice",
    # meat and fish
    "chicken", "chicken breast", "chicken thigh", "ground beef", "beef", "pork", "bacon", "ham",
    "sausage", "salmon", "shrimp", "tuna", "tofu",
}
# Ingredients that come in types. The recipe must name the type, or the line is checked: a bare
# "yeast" or "pasta" cannot be bought correctly. A bare "flour" means all-purpose, the usual meaning.
VARIANT_ALIASES = {
    "flour": "all-purpose flour", "all purpose flour": "all-purpose flour", "ap flour": "all-purpose flour",
    "plain flour": "all-purpose flour", "white flour": "all-purpose flour",
    "bread flour": "bread flour", "cake flour": "cake flour", "pastry flour": "pastry flour",
    "self rising flour": "self-rising flour", "whole wheat flour": "whole wheat flour",
    "white whole wheat flour": "whole wheat flour", "almond flour": "almond flour", "rye flour": "rye flour",
    "active dry yeast": "active dry yeast", "dry active yeast": "active dry yeast",
    "instant yeast": "instant yeast", "rapid rise yeast": "instant yeast",
    "spaghetti": "spaghetti", "penne": "penne", "rotini": "rotini", "fusilli": "fusilli",
    "elbow macaroni": "elbow macaroni", "macaroni": "elbow macaroni", "fettuccine": "fettuccine",
    "linguine": "linguine", "rigatoni": "rigatoni", "ziti": "ziti", "orzo": "orzo",
    "bow tie pasta": "bow tie pasta", "farfalle": "bow tie pasta", "angel hair pasta": "angel hair pasta",
    "angel hair": "angel hair pasta", "lasagna noodle": "lasagna noodle", "egg noodle": "egg noodle",
    "unsalted butter": "unsalted butter", "salted butter": "salted butter",
    "clove": "ground cloves", "ground clove": "ground cloves", "ground cloves": "ground cloves",
}
_FLOUR_SPEC = PACKAGES["flour"]
_BUTTER_SPEC = PACKAGES["butter"]
_YEAST_SPEC = {"packs": [(7, "0.25 oz packet"), (113, "4 oz jar")]}
_PASTA_SPEC = {"packs": [(454, "1 lb box")]}
for _name in VARIANT_ALIASES.values():
    if _name.endswith("flour"):
        PACKAGES[_name] = _FLOUR_SPEC
    elif _name.endswith("butter"):
        PACKAGES[_name] = _BUTTER_SPEC
    elif _name.endswith("yeast"):
        PACKAGES[_name] = _YEAST_SPEC
    elif _name.endswith("cloves"):
        PACKAGES[_name] = {"packs": [(45, "1.5 oz jar")]}
    else:
        PACKAGES[_name] = _PASTA_SPEC
KNOWN_INGREDIENTS |= set(VARIANT_ALIASES.values())
KNOWN_INGREDIENTS.add("shortening")

# Outcomes of a recipe, not things you buy. A line naming one of these is a part of the recipe
# (for example "Crust for 1 large pie:" as a sub-heading) and is never added to the list.
NOT_INGREDIENTS = {"crust", "filling", "topping", "frosting", "batter", "dough", "glaze", "marinade",
                   "garnish", "assembly", "streusel"}


def is_part_line(original, key, has_amount):
    """True for sub-headings and outcomes: 'Crust for 1 large pie:', 'Filling', 'For the crust'."""
    if key in NOT_INGREDIENTS:
        return True
    text = original.strip()
    if text.endswith(":"):
        return True
    return not has_amount and re.search(r"\bfor\s+(\d|the|a|an|one)\b", text, re.IGNORECASE) is not None
KNOWN_INGREDIENTS -= {"pasta", "noodle", "yeast", "flour"}


def is_known_key(key):
    return bool(key) and key in KNOWN_INGREDIENTS


def is_known_name(name):
    """True if a stored item name is an ingredient the list recognises."""
    return is_known_key(item_key((name or "").lower().strip()))


def rebuild_items(conn):
    """Recompute every item from the recipe lines it came from: the name, the amount, and merging of
    lines that are the same ingredient. Typed-in items are read the same way when their name is known.
    Run after each change, so rows saved under older rules pick up the current names. The caller commits."""
    items = conn.execute("SELECT id, name, checked FROM shopping_items ORDER BY id").fetchall()
    lines = conn.execute("SELECT id, item_id, text FROM shopping_lines ORDER BY id").fetchall()
    lines_by_item = {}
    for line in lines:
        lines_by_item.setdefault(line["item_id"], []).append(line)

    # One unit per recipe line, or per typed-in item that has no lines.
    units = []  # (checked, key, display, item_id, line_id, parsed_or_None)
    for it in items:
        its_lines = lines_by_item.get(it["id"])
        if its_lines:
            for line in its_lines:
                parsed = parse_ingredient(line["text"])
                if parsed["part"]:
                    # A sub-heading or an outcome saved by an older version: it is not bought.
                    conn.execute("DELETE FROM shopping_lines WHERE id=?", (line["id"],))
                    continue
                units.append((it["checked"], parsed["key"], parsed["name"], it["id"], line["id"], parsed))
        else:
            parsed = parse_ingredient(it["name"])
            if parsed["known"]:
                units.append((it["checked"], parsed["key"], parsed["name"], it["id"], None, parsed))
            else:
                typed = " ".join((it["name"] or "").split())
                units.append((it["checked"], typed.lower(), typed, it["id"], None, None))

    groups = {}
    for unit in units:
        groups.setdefault((unit[0], unit[1]), []).append(unit)

    keep = set()
    for (checked, key), members in groups.items():
        target = min(m[3] for m in members)
        keep.add(target)
        conn.execute("UPDATE shopping_items SET name=? WHERE id=?", (members[0][2], target))
        for _, _, _, _, line_id, parsed in members:
            if line_id is not None:
                conn.execute("UPDATE shopping_lines SET item_id=?, amount=?, grams=?, count=? WHERE id=?",
                             (target, parsed["amount"], parsed["grams"], parsed["count"], line_id))

    for it in items:
        if it["id"] not in keep:
            conn.execute("DELETE FROM shopping_items WHERE id=?", (it["id"],))
