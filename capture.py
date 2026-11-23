"""Turn photos of handwritten recipes or cookbook pages into a draft recipe.

Uses the Tesseract OCR program (installed by the Dockerfile). Results are a best guess:
the recipe is created for you to review and correct on its edit page.
"""
import re
import shutil
import subprocess

OCR_TIMEOUT_SECONDS = 30
MAX_CAPTURE_PAGES = 8
UNIT_WORDS = (r"cups?|tbsps?|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|"
              r"l|liters?|litres?|pinch|dash|cloves?|cans?|pkgs?|packages?|sticks?|slices?|"
              r"pieces?|large|medium|small")
INGREDIENT_START = re.compile(r"^(\d|[¼½¾⅓⅔⅛]|(" + UNIT_WORDS + r")\b)", re.IGNORECASE)
INGREDIENT_HEADER = re.compile(r"^\W*ingredients\W*$", re.IGNORECASE)
STEP_HEADER = re.compile(r"^\W*(directions?|instructions?|method|steps?|preparation|procedure)\W*$",
                         re.IGNORECASE)
STEP_NUMBER = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+")


def tesseract_available():
    return shutil.which("tesseract") is not None


def ocr_image(path):
    """Read the text on one photo. Raises RuntimeError with a plain message on failure."""
    if not tesseract_available():
        raise RuntimeError("The text reader isn't installed on this server yet.")
    try:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=OCR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("That photo took too long to read. Try a closer, smaller photo.")
    if result.returncode != 0:
        raise RuntimeError("That photo couldn't be read. Try a clearer photo.")
    return result.stdout


def clean_line(line):
    line = line.replace("|", " ").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", line).strip(" \t-•*·")


def parse_recipe_text(text):
    """Split OCR text into a draft: title, ingredients, steps, and notes for anything unclear."""
    lines = [clean_line(l) for l in text.splitlines()]
    lines = [l for l in lines if l]

    title = ""
    ingredients, steps, notes = [], [], []
    section = None  # None (before any header), "ingredients", "steps"
    has_headers = any(INGREDIENT_HEADER.match(l) or STEP_HEADER.match(l) for l in lines)

    for line in lines:
        if INGREDIENT_HEADER.match(line):
            section = "ingredients"
            continue
        if STEP_HEADER.match(line):
            section = "steps"
            continue

        if section == "ingredients":
            ingredients.append(line)
        elif section == "steps":
            steps.append(STEP_NUMBER.sub("", line))
        elif not has_headers:
            # No headers on the page: lines that start with an amount are ingredients.
            if not title and len(line) <= 80 and not INGREDIENT_START.match(line):
                title = line
            elif INGREDIENT_START.match(line) and len(line) <= 120:
                ingredients.append(line)
            else:
                steps.append(STEP_NUMBER.sub("", line))
        else:
            # Lines before the first header: the first short line is the title.
            if not title and len(line) <= 80:
                title = line
            else:
                notes.append(line)

    if not title:
        title = "Scanned recipe"
    return {
        "title": title[:120],
        "ingredients": "\n".join(ingredients),
        "steps": "\n".join(steps),
        "notes": "\n".join(notes),
    }
