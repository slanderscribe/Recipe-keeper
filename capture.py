"""Turn recipe files into a draft recipe: photos, scanned pages, PDFs, Word and text files.

Two readers:
- Claude's vision model (used when ANTHROPIC_API_KEY is set). Reads handwriting, cookbook
  layouts and PDFs, and sees all the files together so a recipe split across pages comes
  out whole.
- Free fallback: text is read straight out of text, Word and PDF files; photos and scanned
  PDF pages go through Tesseract OCR (good on printed text, weak on handwriting).

Results are a best guess: the recipe is created for you to review on its edit page.
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import requests
from PIL import Image, ImageOps

MAX_CAPTURE_PAGES = 8
TESSERACT_TIMEOUT_SECONDS = 30
CLAUDE_TIMEOUT_SECONDS = 150
CLAUDE_MODEL = os.environ.get("CAPTURE_MODEL", "claude-sonnet-5-5")
MAX_IMAGE_SIDE = 2000

IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
PDF_EXTS = {"pdf"}
WORD_EXTS = {"docx"}
TEXT_EXTS = {"txt", "md"}
CAPTURE_EXTS = IMAGE_EXTS | PDF_EXTS | WORD_EXTS | TEXT_EXTS

UNIT_WORDS = (r"cups?|tbsps?|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|g|grams?|kg|ml|"
              r"l|liters?|litres?|pinch|dash|cloves?|cans?|pkgs?|packages?|sticks?|slices?|"
              r"pieces?|large|medium|small")
INGREDIENT_START = re.compile(r"^(\d|[¼½¾⅓⅔⅛]|(" + UNIT_WORDS + r")\b)", re.IGNORECASE)
INGREDIENT_HEADER = re.compile(r"^\W*ingredients\W*$", re.IGNORECASE)
STEP_HEADER = re.compile(r"^\W*(directions?|instructions?|method|steps?|preparation|procedure)\W*$",
                         re.IGNORECASE)
NOTES_HEADER = re.compile(r"^\W*(notes?|tips?)\W*$", re.IGNORECASE)
STEP_NUMBER = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+")
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

CLAUDE_PROMPT = (
    "These files hold one recipe: photos of a handwritten card or cookbook page, scanned pages, "
    "PDFs or text documents. Read them in the order given, treating them as consecutive parts of "
    "one recipe. Read every word and return only JSON with these keys:\n"
    '- "title": string, the recipe name.\n'
    '- "ingredients": array of strings, one per ingredient, keeping quantities and units exactly as '
    "written. Include sub-lists such as syrup or dry ingredients as their own lines.\n"
    '- "steps": array of strings, one per instruction, in order, without step numbers.\n'
    '- "notes": string with anything that does not fit above, such as oven temperature, servings, '
    "or times. Use an empty string if there is nothing.\n"
    "Copy the wording exactly. Do not correct, translate or add anything. If a word is unreadable, "
    "write [unclear] in its place. Output the JSON only."
)


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_image(path):
    return ext_of(path) in IMAGE_EXTS


def claude_key():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def tesseract_available():
    return shutil.which("tesseract") is not None


def capture_ready():
    """True when at least one reader is available."""
    return bool(claude_key()) or tesseract_available()


def clean_line(line):
    line = line.replace("|", " ").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", line).strip(" \t-•*·")


# ---------- reading text straight out of files ----------

def text_from_plain(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def text_from_docx(path):
    """Word files are zipped XML; pull the text out of each paragraph."""
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        raise RuntimeError("That Word file couldn't be opened. Try saving it again as .docx.")
    paragraphs = ("".join(t.text or "" for t in p.iter(WORD_NS + "t")) for p in root.iter(WORD_NS + "p"))
    return "\n".join(paragraphs)


def text_from_pdf(path):
    from pypdf import PdfReader
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        raise RuntimeError("That PDF couldn't be opened. Try exporting it again.")


def pdf_page_images(path, folder):
    """Scanned PDFs have no text layer: turn each page into a picture for OCR."""
    if not shutil.which("pdftoppm"):
        raise RuntimeError("That PDF is a scan and this server can't read scans yet.")
    prefix = os.path.join(folder, "page")
    subprocess.run(["pdftoppm", "-r", "200", "-png", path, prefix],
                   capture_output=True, timeout=TESSERACT_TIMEOUT_SECONDS * 4, check=False)
    return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.startswith("page"))


# ---------- Claude vision reader ----------

def _jpeg_bytes(path):
    """Shrink phone photos so each upload stays small and quick."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()


def _parse_json_reply(text):
    match = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if not match:
        raise ValueError("no JSON in reply")
    return json.loads(match.group(0))


def _claude_block(path):
    ext = ext_of(path)
    name = os.path.basename(path)
    if ext in IMAGE_EXTS:
        data = base64.b64encode(_jpeg_bytes(path)).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
    if ext in PDF_EXTS:
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    if ext in WORD_EXTS:
        body = text_from_docx(path)
    else:
        body = text_from_plain(path)
    return {"type": "text", "text": f"Document {name}:\n{body}"}


def read_with_claude(paths):
    content = [_claude_block(p) for p in paths]
    content.append({"type": "text", "text": CLAUDE_PROMPT})
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": claude_key(), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": content}]},
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        raise RuntimeError("The reader couldn't be reached. Check the connection and try again.")
    if resp.status_code != 200:
        print("capture: Claude API error", resp.status_code, resp.text[:300], flush=True)
        raise RuntimeError("The reader couldn't process these files. Try again in a minute, or use "
                           "smaller files.")
    text = "".join(block.get("text", "") for block in resp.json().get("content", [])
                   if block.get("type") == "text")
    try:
        data = _parse_json_reply(text)
    except (ValueError, json.JSONDecodeError):
        raise RuntimeError("The reader returned something unexpected. Try again with clearer files.")

    def lines(value):
        items = value if isinstance(value, list) else str(value or "").splitlines()
        return [clean_line(str(v)) for v in items if clean_line(str(v))]

    title = " ".join(lines(data.get("title"))[:1]) or "Scanned recipe"
    return {
        "title": title[:120],
        "ingredients": "\n".join(lines(data.get("ingredients"))),
        "steps": "\n".join(lines(data.get("steps"))),
        "notes": "\n".join(lines(data.get("notes"))),
    }


# ---------- free fallback ----------

def ocr_image(path):
    """Read the text on one photo with Tesseract. Raises RuntimeError with a plain message."""
    if not tesseract_available():
        raise RuntimeError("No text reader is set up on this server yet.")
    try:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=TESSERACT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("That photo took too long to read. Try a closer, smaller photo.")
    if result.returncode != 0:
        raise RuntimeError("That photo couldn't be read. Try a clearer photo.")
    return result.stdout


def parse_recipe_text(text):
    """Split text into a draft: title, ingredients, steps, and notes for anything unclear."""
    lines = [l for l in (clean_line(raw) for raw in text.splitlines()) if l]

    title = ""
    ingredients, steps, notes = [], [], []
    section = None  # None, "ingredients", "steps", "notes"
    has_headers = any(INGREDIENT_HEADER.match(l) or STEP_HEADER.match(l) for l in lines)

    for line in lines:
        if INGREDIENT_HEADER.match(line):
            section = "ingredients"
            continue
        if STEP_HEADER.match(line):
            section = "steps"
            continue
        if NOTES_HEADER.match(line):
            section = "notes"
            continue

        if section == "ingredients":
            ingredients.append(line)
        elif section == "steps":
            steps.append(STEP_NUMBER.sub("", line))
        elif section == "notes":
            notes.append(line)
        elif not has_headers:
            if not title and len(line) <= 80 and not INGREDIENT_START.match(line):
                title = line
            elif INGREDIENT_START.match(line) and len(line) <= 120:
                ingredients.append(line)
            else:
                steps.append(STEP_NUMBER.sub("", line))
        else:
            if not title and len(line) <= 80:
                title = line
            else:
                notes.append(line)

    return {
        "title": (title or "Scanned recipe")[:120],
        "ingredients": "\n".join(ingredients),
        "steps": "\n".join(steps),
        "notes": "\n".join(notes),
    }


def text_from_file(path, folder):
    """Plain text from one file for the free reader. Photos and scanned PDFs go through OCR."""
    ext = ext_of(path)
    if ext in TEXT_EXTS:
        return text_from_plain(path)
    if ext in WORD_EXTS:
        return text_from_docx(path)
    if ext in PDF_EXTS:
        text = text_from_pdf(path)
        if text.strip():
            return text
        return "\n".join(ocr_image(page) for page in pdf_page_images(path, folder))
    return ocr_image(path)


def read_recipe(paths):
    """Read the files, in order, into a draft recipe. Uses Claude when a key is set."""
    if claude_key():
        return read_with_claude(paths)
    with tempfile.TemporaryDirectory() as folder:
        text = "\n".join(text_from_file(p, folder) for p in paths)
    if not text.strip():
        raise RuntimeError("No readable text was found in those files.")
    return parse_recipe_text(text)
