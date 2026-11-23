"""Pulls recipe details out of links shared from social media and recipe websites.

Recipe sites usually publish schema.org "Recipe" data (JSON-LD), which gives clean
ingredients and steps. Social sites rarely do, so for those we keep the post's
title, caption and photo and store the link, which the app can also embed.
"""
import html as htmllib
import ipaddress
import json
import os
import re
import socket
import uuid
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MAX_BYTES = 2_000_000
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
PLATFORM_DOMAINS = {
    "instagram": ["instagram.com", "instagr.am"],
    "tiktok": ["tiktok.com"],
    "youtube": ["youtube.com", "youtu.be"],
    "facebook": ["facebook.com", "fb.watch", "fb.com"],
    "pinterest": ["pinterest.com", "pin.it"],
    "threads": ["threads.net"],
    "x": ["x.com", "twitter.com"],
}
SOCIAL_PLATFORMS = set(PLATFORM_DOMAINS)


class ImportProblem(Exception):
    """A plain-language reason an import could not finish."""


# ---------- URLs and platforms ----------

def normalize_url(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def extract_first_url(text):
    match = re.search(r"https?://[^\s\"'<>]+", text or "")
    return match.group(0).rstrip(".,);!") if match else ""


def detect_platform(url):
    if not url:
        return ""
    host = urlparse(url).netloc.lower().split(":")[0]
    for name, domains in PLATFORM_DOMAINS.items():
        for domain in domains:
            if host == domain or host.endswith("." + domain):
                return name
    return "web"


def embed_src(url):
    """Return an embeddable player address for YouTube, TikTok or Instagram links, else None."""
    if not url:
        return None
    platform = detect_platform(url)
    if platform == "youtube":
        match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{6,})", url)
        return f"https://www.youtube.com/embed/{match.group(1)}" if match else None
    if platform == "tiktok":
        match = re.search(r"/video/(\d+)", url)
        return f"https://www.tiktok.com/embed/v2/{match.group(1)}" if match else None
    if platform == "instagram":
        match = re.search(r"/(p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
        if not match:
            return None
        kind = {"p": "p", "tv": "tv"}.get(match.group(1), "reel")
        return f"https://www.instagram.com/{kind}/{match.group(2)}/embed"
    return None


def is_safe_url(url):
    """Refuse addresses that point at this server's own network."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def fetch_html(url):
    current = url
    for _ in range(4):
        if not is_safe_url(current):
            raise ImportProblem("That address can't be opened.")
        try:
            resp = requests.get(current, headers=HEADERS, timeout=12,
                                allow_redirects=False, stream=True)
        except requests.RequestException:
            raise ImportProblem("Couldn't reach that page. Check the link and try again.")
        try:
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                current = urljoin(current, resp.headers["Location"])
                continue
            if resp.status_code >= 400:
                raise ImportProblem(f"The site returned an error ({resp.status_code}).")
            body = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    break
            return body.decode("utf-8", errors="replace"), current
        finally:
            resp.close()
    raise ImportProblem("That link redirected too many times.")


IMAGE_TYPES = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
               "image/webp": "webp", "image/gif": "gif"}
MAX_IMAGE_BYTES = 10_000_000


def download_image(url, dest_dir, referer=""):
    """Save a copy of a remote photo in dest_dir so the recipe keeps it. Returns the file name, or ''."""
    if not is_safe_url(url):
        return ""
    headers = dict(HEADERS, Referer=referer) if referer else HEADERS
    try:
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=False, stream=True)
    except requests.RequestException:
        return ""
    try:
        if resp.status_code != 200:
            return ""
        ext = IMAGE_TYPES.get(resp.headers.get("Content-Type", "").split(";")[0].strip().lower())
        if not ext:
            return ""
        body = bytearray()
        for chunk in resp.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > MAX_IMAGE_BYTES:
                return ""
        name = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(dest_dir, name), "wb") as handle:
            handle.write(body)
        return name
    finally:
        resp.close()


# ---------- parsing ----------

def clean_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def text_of(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("text") or ""
    return clean_text(value)


def iso_minutes(value):
    """Convert ISO 8601 durations like PT1H30M into minutes, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    match = re.match(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$", text)
    if match:
        days, hours, mins = (int(x) if x else 0 for x in match.groups())
        return (days * 1440 + hours * 60 + mins) or None
    match = re.search(r"(\d+)\s*MIN", text)
    return int(match.group(1)) if match else None


def find_recipe_node(node):
    if isinstance(node, list):
        for item in node:
            found = find_recipe_node(item)
            if found:
                return found
        return None
    if not isinstance(node, dict):
        return None
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    if "Recipe" in types:
        return node
    if "@graph" in node:
        return find_recipe_node(node["@graph"])
    return None


def flatten_steps(instructions):
    steps = []
    if isinstance(instructions, str):
        steps = [clean_text(line) for line in instructions.splitlines()]
    elif isinstance(instructions, list):
        for item in instructions:
            steps.extend(flatten_steps(item))
    elif isinstance(instructions, dict):
        if "itemListElement" in instructions:
            steps.extend(flatten_steps(instructions["itemListElement"]))
        else:
            steps.append(clean_text(instructions.get("text") or instructions.get("name") or ""))
    return [s for s in steps if s]


def first_image(image):
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        return first_image(image[0])
    if isinstance(image, dict):
        return image.get("url") or image.get("@id") or ""
    return ""


def parse_page(page_html, url):
    """Return (draft, has_full_recipe). The draft uses the same field names as the recipe form."""
    soup = BeautifulSoup(page_html, "html.parser")
    recipe = None
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        recipe = find_recipe_node(payload)
        if recipe:
            break

    meta = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").lower()
        content = (tag.get("content") or "").strip()
        if key and content and key not in meta:
            meta[key] = content
    title_tag = soup.title.string if soup.title and soup.title.string else ""

    draft = {
        "title": "", "description": "", "servings": "", "prep_minutes": None,
        "cook_minutes": None, "ingredients": "", "steps": "", "notes": "", "tags": "",
        "rating": None, "source_url": url, "source_platform": detect_platform(url),
        "source_author": "", "cover_image": "",
    }

    if recipe:
        draft["title"] = text_of(recipe.get("name"))
        draft["description"] = text_of(recipe.get("description"))
        draft["servings"] = text_of(recipe.get("recipeYield"))
        draft["prep_minutes"] = iso_minutes(recipe.get("prepTime"))
        draft["cook_minutes"] = iso_minutes(recipe.get("cookTime"))
        ingredients = recipe.get("recipeIngredient") or []
        if isinstance(ingredients, str):
            ingredients = ingredients.splitlines()
        draft["ingredients"] = "\n".join(c for c in (clean_text(i) for i in ingredients) if c)
        draft["steps"] = "\n".join(flatten_steps(recipe.get("recipeInstructions")))
        draft["source_author"] = text_of(recipe.get("author"))
        # Auto-sorting attaches only the first two categories a recipe site lists.
        raw = recipe.get("recipeCategory") or []
        if isinstance(raw, str):
            raw = raw.split(",")
        names = [clean_text(part) for part in raw if clean_text(part)]
        draft["category"] = ",".join(names[:2])
        image = first_image(recipe.get("image"))
        draft["cover_image"] = urljoin(url, image) if image else ""

    if not draft["title"]:
        draft["title"] = clean_text(meta.get("og:title") or meta.get("twitter:title") or title_tag)
    if not draft["description"]:
        draft["description"] = clean_text(meta.get("og:description") or meta.get("description") or "")
    if not draft["cover_image"]:
        image = meta.get("og:image") or meta.get("twitter:image") or ""
        draft["cover_image"] = urljoin(url, image) if image else ""

    return draft, bool(recipe and draft["ingredients"])


def import_from_url(url, dest_dir=None):
    """Return (draft, message) for a link. Raises ImportProblem for links we can't use at all.

    When dest_dir is given, the recipe photo is copied there so it doesn't depend on the source site.
    """
    platform = detect_platform(url)
    try:
        page_html, final_url = fetch_html(url)
    except ImportProblem:
        if platform in SOCIAL_PLATFORMS:
            draft = {
                "title": "", "description": "", "servings": "", "prep_minutes": None,
                "cook_minutes": None, "ingredients": "", "steps": "", "notes": "", "tags": "",
                "rating": None, "source_url": url, "source_platform": platform,
                "source_author": "", "cover_image": "",
            }
            label = platform.capitalize()
            return draft, (f"{label} wouldn't share the post details with the app, so the link is saved. "
                           "Paste the caption into Ingredients and Steps, and add a photo or video.")
        raise

    draft, full = parse_page(page_html, final_url)
    draft["source_url"] = url
    draft["source_platform"] = platform
    if dest_dir and draft["cover_image"].startswith(("http://", "https://")):
        saved = download_image(draft["cover_image"], dest_dir, referer=final_url)
        draft["cover_image"] = saved or draft["cover_image"]

    if full:
        message = "Found a full recipe on the page. Check the details, then save."
    elif platform in SOCIAL_PLATFORMS:
        message = (f"Pulled the title, caption and photo from {platform.capitalize()}. Social sites hide "
                   "most of the detail, so fill in the ingredients and steps.")
    else:
        message = ("This page has no structured recipe, so only the title and photo came through. "
                   "Add the ingredients and steps by hand.")
    return draft, message
