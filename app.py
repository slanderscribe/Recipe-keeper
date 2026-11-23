"""Recipe Keeper: a family recipe box with social-post import, mixed media and a shopping list."""
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for, jsonify)

from shopping import (combined_amounts, is_known_name, item_key, parse_ingredient, parse_quantity,
                      purchase_text, rebuild_items)
from capture import CAPTURE_EXTS, MAX_CAPTURE_PAGES, capture_ready, claude_key, read_recipe
from importers import (ImportProblem, detect_platform, embed_src,
                       extract_first_url, import_from_url, normalize_url)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "recipes.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp"}
VIDEO_EXTS = {"mp4", "mov", "webm", "m4v"}
DEFAULT_CATEGORIES = ["Breakfast", "Lunch", "Dinner", "Dessert", "Baking", "Snacks",
                      "Appetizers", "Soups & Salads", "Sides", "Drinks"]
# Common custom groupings offered as suggestions (they only attach to a recipe once you pick them).
SUGGESTED_CATEGORIES = ["Holiday", "Christmas", "Thanksgiving", "Easter", "Birthday", "Party",
                        "Game day", "Date night", "Weeknight", "Meal prep", "Kid-approved",
                        "Vegetarian", "Gluten-free", "Summer", "Winter"]

app = Flask(__name__)
# Template check: is this ingredient line a sub-heading or a recipe part rather than something to buy?
app.jinja_env.filters["is_part"] = lambda text: parse_ingredient(text)["part"]
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    f"recipe-keeper:{APP_PASSWORD}".encode()).hexdigest()
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
# "Keep this device signed in" lasts a year. Cookies are only marked Secure on Railway (HTTPS).
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RAILWAY_ENVIRONMENT_NAME"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    servings TEXT NOT NULL DEFAULT '',
    prep_minutes INTEGER,
    cook_minutes INTEGER,
    ingredients TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    rating INTEGER,
    source_url TEXT NOT NULL DEFAULT '',
    source_author TEXT NOT NULL DEFAULT '',
    source_platform TEXT NOT NULL DEFAULT '',
    cover_image TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shopping_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
-- One line per recipe ingredient that feeds a shopping item (several recipes can share one item).
CREATE TABLE IF NOT EXISTS shopping_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES shopping_items(id) ON DELETE CASCADE,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    recipe_title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    amount TEXT NOT NULL DEFAULT '',
    grams REAL,
    count REAL,
    created_at TEXT NOT NULL
);
"""

INSERT_SQL = """
INSERT INTO recipes (title, description, servings, prep_minutes, cook_minutes, ingredients,
    steps, notes, tags, rating, source_url, source_author, source_platform, cover_image,
    category, created_at, updated_at)
VALUES (:title, :description, :servings, :prep_minutes, :cook_minutes, :ingredients,
    :steps, :notes, :tags, :rating, :source_url, :source_author, :source_platform,
    :cover_image, :category, :created_at, :updated_at)
"""

UPDATE_SQL = """
UPDATE recipes SET title=:title, description=:description, servings=:servings,
    prep_minutes=:prep_minutes, cook_minutes=:cook_minutes, ingredients=:ingredients,
    steps=:steps, notes=:notes, tags=:tags, rating=:rating, source_url=:source_url,
    source_author=:source_author, source_platform=:source_platform,
    cover_image=:cover_image, category=:category, updated_at=:updated_at
WHERE id=:id
"""


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        # Older databases (created before categories existed) get the new column added.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recipes)")}
        if "category" not in columns:
            conn.execute("ALTER TABLE recipes ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


init_db()


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------- helpers ----------

def to_int(value):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def clean_lines(text):
    return "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())


def split_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def cover_url(value):
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return url_for("uploaded_file", filename=value)


@app.context_processor
def template_helpers():
    count = get_db().execute(
        "SELECT COUNT(*) FROM shopping_items WHERE checked = 0").fetchone()[0]
    return {
        "category_options": sorted(all_category_names().values()),
        "shopping_count": count,
        "logged_in": bool(APP_PASSWORD),
        "embed_src": embed_src,
        "detect_platform": detect_platform,
        "cover_url": cover_url,
        "max_mb": MAX_UPLOAD_MB,
    }


def canonical_category(raw):
    """Match a typed category to a default name regardless of case ("dessert" -> "Dessert")."""
    name = " ".join((raw or "").split())
    known = {c.lower(): c for c in DEFAULT_CATEGORIES + SUGGESTED_CATEGORIES}
    return known.get(name.lower(), name[:40])


def recipe_from_form(form):
    source_url = normalize_url(form.get("source_url", ""))
    rating = to_int(form.get("rating"))
    tags = [t.strip().lower().replace(" ", "-") for t in form.get("tags", "").split(",") if t.strip()]
    return {
        "title": form.get("title", "").strip(),
        "description": form.get("description", "").strip(),
        "servings": form.get("servings", "").strip(),
        "prep_minutes": to_int(form.get("prep_minutes")),
        "cook_minutes": to_int(form.get("cook_minutes")),
        "ingredients": clean_lines(form.get("ingredients")),
        "steps": clean_lines(form.get("steps")),
        "notes": form.get("notes", "").strip(),
        "tags": ",".join(dict.fromkeys(tags)),
        "rating": rating if rating in (1, 2, 3, 4, 5) else None,
        "source_url": source_url,
        "source_author": form.get("source_author", "").strip(),
        "source_platform": detect_platform(source_url) if source_url else "",
        "cover_image": form.get("cover_image", "").strip(),
        "category": ",".join(dict.fromkeys(canonical_category(c) for c in split_categories(form.get("category", "")))),
    }


def save_files(files, exts):
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in exts:
            flash(f"Skipped {f.filename}: that file type isn't supported.", "warn")
            continue
        name = f"{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(UPLOAD_DIR, name))
        saved.append(name)
    return saved


def remove_upload(name):
    if name and os.path.basename(name) == name:
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path):
            os.remove(path)


def add_media(recipe_id, kind, filename="", url=""):
    get_db().execute(
        "INSERT INTO media (recipe_id, kind, filename, url, created_at) VALUES (?, ?, ?, ?, ?)",
        (recipe_id, kind, filename, url, now()))


def attach_media(recipe_id, form, files):
    """Store uploaded photos, videos and pasted links. Returns the saved photo names."""
    photos = save_files(files.getlist("photos"), IMAGE_EXTS)
    videos = save_files(files.getlist("videos"), VIDEO_EXTS)
    for name in photos:
        add_media(recipe_id, "image", filename=name)
    for name in videos:
        add_media(recipe_id, "video", filename=name)
    for raw in split_lines(form.get("links", "")):
        url = normalize_url(raw)
        if url and " " not in url and "." in url:
            add_media(recipe_id, "link", url=url)
    return photos


def run_import(raw_url):
    url = normalize_url(raw_url)
    if not url:
        flash("Paste a link first.", "error")
        return {}
    try:
        draft, message = import_from_url(url, UPLOAD_DIR)
        flash(message, "ok")
        return draft
    except ImportProblem as exc:
        flash(str(exc), "error")
        return {"source_url": url, "source_platform": detect_platform(url)}


# ---------- login ----------

@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint in ("login", "static"):
        return None
    if session.get("ok"):
        return None
    return redirect(url_for("login", next=request.full_path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    if request.method == "POST":
        typed = request.form.get("password", "").encode()
        if hmac.compare_digest(typed, APP_PASSWORD.encode()):
            session.clear()
            session["ok"] = True
            session.permanent = bool(request.form.get("remember"))
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("index")
            return redirect(nxt)
        flash("That password isn't right.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login") if APP_PASSWORD else url_for("index"))


@app.errorhandler(413)
def too_large(_err):
    flash(f"That upload is too big. The limit is {MAX_UPLOAD_MB} MB per request.", "error")
    return redirect(request.referrer or url_for("index"))


# ---------- recipes ----------

UNCATEGORIZED = "Uncategorized"


def split_categories(value):
    """A recipe can have several categories, stored as 'Dessert,Holiday'."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def all_category_names():
    """Every category name in use, keyed by lowercase, with default names first."""
    names = {c.lower(): c for c in DEFAULT_CATEGORIES}
    for row in get_db().execute("SELECT category FROM recipes WHERE category != ''"):
        for name in split_categories(row[0]):
            names.setdefault(name.lower(), name)
    return names


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip().lower()
    cat = request.args.get("cat", "").strip()
    db = get_db()

    # Category tabs: every default category, any custom ones in use, and recipes with none.
    all_rows = db.execute("SELECT category, tags FROM recipes").fetchall()
    display, counts, uncategorized, tag_set = {}, {}, 0, set()
    for row in all_rows:
        tag_set.update(t for t in row["tags"].split(",") if t)
        names = split_categories(row["category"])
        if not names:
            uncategorized += 1
        for name in dict.fromkeys(names):
            key = name.lower()
            display.setdefault(key, name)
            counts[key] = counts.get(key, 0) + 1
    defaults = {c.lower(): c for c in DEFAULT_CATEGORIES}
    for key, name in defaults.items():
        display.setdefault(key, name)
    custom_keys = sorted(k for k in counts if k not in defaults)
    categories = [{"name": display[k], "n": counts.get(k, 0)} for k in list(defaults) + custom_keys]
    if uncategorized:
        categories.append({"name": UNCATEGORIZED, "n": uncategorized})

    sql = "SELECT * FROM recipes WHERE 1=1"
    params = []
    if q:
        sql += (" AND (title LIKE ? OR description LIKE ? OR ingredients LIKE ?"
                " OR tags LIKE ? OR source_author LIKE ? OR category LIKE ?)")
        params += [f"%{q}%"] * 6
    if cat == UNCATEGORIZED:
        sql += " AND TRIM(category) = ''"
    elif cat:
        sql += " AND (',' || lower(category) || ',') LIKE ?"
        params.append(f"%,{cat.lower()},%")
    if tag:
        sql += " AND (',' || tags || ',') LIKE ?"
        params.append(f"%,{tag},%")
    sql += " ORDER BY updated_at DESC"
    recipes = db.execute(sql, params).fetchall()
    return render_template("index.html", recipes=recipes, q=q, tag=tag, cat=cat,
                           categories=categories, total=len(all_rows), all_tags=sorted(tag_set))


@app.route("/suggest")
def suggest():
    """Live suggestions while typing in the search box: categories, tags, titles and authors."""
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])
    db = get_db()
    if request.args.get("kind") == "category":
        # Category boxes on the recipe form: only category names, alphabetical.
        names = all_category_names()
        for event in SUGGESTED_CATEGORIES:
            names.setdefault(event.lower(), event)
        matches = [name for name in names.values()
                   if name.lower().startswith(q) or any(w.startswith(q) for w in name.lower().split())]
        return jsonify(sorted(matches, key=str.lower)[:8])
    pool = {}
    for name in DEFAULT_CATEGORIES + SUGGESTED_CATEGORIES:
        pool.setdefault(name.lower(), name)
    for row in db.execute("SELECT category, tags, title, source_author FROM recipes").fetchall():
        candidates = [row["category"], row["title"], row["source_author"]]
        candidates += [t.replace("-", " ") for t in row["tags"].split(",") if t]
        for value in candidates:
            value = (value or "").strip()
            if value:
                pool.setdefault(value.lower(), value)
    scored = []
    for low, shown in pool.items():
        words = [w for w in re.split(r"[\s\-,&/]+", low) if w]
        if low.startswith(q):
            score = 0
        elif any(w.startswith(q) for w in words):
            score = 1
        elif q in low:
            score = 2
        else:
            continue
        scored.append((score, low, shown))
    scored.sort()
    return jsonify([shown for _score, _low, shown in scored[:8]])


@app.route("/recipes/new", methods=["GET", "POST"])
def new_recipe():
    if request.method == "POST":
        data = recipe_from_form(request.form)
        if not data["title"]:
            flash("Give the recipe a title before saving.", "error")
            return render_template("recipe_form.html", recipe=data, mode="new")
        stamp = now()
        db = get_db()
        cur = db.execute(INSERT_SQL, {**data, "created_at": stamp, "updated_at": stamp})
        recipe_id = cur.lastrowid
        photos = attach_media(recipe_id, request.form, request.files)
        if photos and not data["cover_image"]:
            db.execute("UPDATE recipes SET cover_image=? WHERE id=?", (photos[0], recipe_id))
        db.commit()
        flash("Recipe saved.", "ok")
        return redirect(url_for("view_recipe", recipe_id=recipe_id))
    return render_template("recipe_form.html", recipe={}, mode="new")


def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def save_shared(files, values):
    """Create a recipe from files shared from the phone, such as a video saved from TikTok."""
    link = normalize_url(values.get("url", "")) or extract_first_url(values.get("text", ""))
    title = (values.get("title") or "").strip() or "Shared recipe"
    data = recipe_from_form({"title": title, "source_url": link})
    stamp = now()
    db = get_db()
    cur = db.execute(INSERT_SQL, {**data, "created_at": stamp, "updated_at": stamp})
    recipe_id = cur.lastrowid
    photos = save_files([f for f in files if ext_of(f.filename) in IMAGE_EXTS], IMAGE_EXTS)
    clips = save_files([f for f in files if ext_of(f.filename) in VIDEO_EXTS], VIDEO_EXTS)
    for name in photos:
        add_media(recipe_id, "image", filename=name)
    for name in clips:
        add_media(recipe_id, "video", filename=name)
    if photos:
        db.execute("UPDATE recipes SET cover_image=? WHERE id=?", (photos[0], recipe_id))
    db.commit()
    flash("Saved to Recipe Keeper. Add the ingredients and steps, then save.", "ok")
    return redirect(url_for("edit_recipe", recipe_id=recipe_id))


@app.route("/import", methods=["GET", "POST"])
def import_link():
    """Import a link, or save files shared from the phone (the share target posts here)."""
    shared = [f for f in request.files.getlist("media") if f and f.filename]
    if shared:
        return save_shared(shared, request.values)
    raw = (request.values.get("url") or extract_first_url(request.values.get("text", ""))
           or extract_first_url(request.values.get("title", "")))
    if not raw:
        flash("No link came through. Paste one below.", "warn")
        return redirect(url_for("new_recipe"))
    draft = run_import(raw)
    return render_template("recipe_form.html", recipe=draft, mode="new")


@app.route("/capture", methods=["GET", "POST"])
def capture():
    """Scan handwritten recipes or cookbook pages into a draft recipe."""
    if request.method == "GET":
        return render_template("capture.html", ready=capture_ready(), using_claude=bool(claude_key()),
                               max_pages=MAX_CAPTURE_PAGES)
    pages = [f for f in request.files.getlist("pages") if f and f.filename]
    if not pages:
        flash("Choose at least one photo.", "warn")
        return redirect(url_for("capture"))
    if len(pages) > MAX_CAPTURE_PAGES:
        flash(f"Scan up to {MAX_CAPTURE_PAGES} pages at a time. Do the rest in a second batch.", "warn")
        return redirect(url_for("capture"))
    saved = save_files(pages, CAPTURE_EXTS)
    if not saved:
        return redirect(url_for("capture"))
    try:
        draft = read_recipe([os.path.join(UPLOAD_DIR, name) for name in saved])
    except RuntimeError as exc:
        for name in saved:
            remove_upload(name)
        flash(str(exc), "error")
        return redirect(url_for("capture"))
    data = recipe_from_form({"title": draft["title"], "ingredients": draft["ingredients"],
                             "steps": draft["steps"], "notes": draft["notes"]})
    stamp = now()
    db = get_db()
    cur = db.execute(INSERT_SQL, {**data, "created_at": stamp, "updated_at": stamp})
    recipe_id = cur.lastrowid
    photos = [name for name in saved if ext_of(name) in IMAGE_EXTS]
    for name in saved:
        # Photos show in the gallery; PDFs and Word or text files are kept as downloadable originals.
        add_media(recipe_id, "image" if name in photos else "document", filename=name)
    # The first photo is the recipe picture until you replace it with a photo of the finished dish.
    if photos:
        db.execute("UPDATE recipes SET cover_image=? WHERE id=?", (photos[0], recipe_id))
    db.commit()
    count = len(saved)
    flash(f"Read {count} file{'s' if count != 1 else ''}. Check the text against the original and fix "
          "anything the reader got wrong, then save.", "ok")
    return redirect(url_for("edit_recipe", recipe_id=recipe_id))


def build_share_text(row):
    """One plain-text page for a recipe: pastes cleanly into messages, email and notes."""
    lines = [row["title"]]
    facts = []
    if row["servings"]:
        facts.append(f"Serves {row['servings']}")
    if row["prep_minutes"]:
        facts.append(f"Prep {row['prep_minutes']} min")
    if row["cook_minutes"]:
        facts.append(f"Cook {row['cook_minutes']} min")
    if facts:
        lines.append(" | ".join(facts))
    if row["description"]:
        lines += ["", row["description"]]
    ingredients = split_lines(row["ingredients"])
    if ingredients:
        lines += ["", "Ingredients"] + [f"- {item}" for item in ingredients]
    steps = split_lines(row["steps"])
    if steps:
        lines += ["", "Steps"] + [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    if row["notes"]:
        lines += ["", "Notes", row["notes"]]
    if row["source_url"]:
        lines += ["", f"Original: {row['source_url']}"]
    return "\n".join(lines) + "\n"


@app.route("/recipes/<int:recipe_id>/share.txt")
def share_text(recipe_id):
    row = get_db().execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not row:
        abort(404)
    return Response(build_share_text(row), mimetype="text/plain; charset=utf-8")


@app.route("/recipes/<int:recipe_id>")
def view_recipe(recipe_id):
    db = get_db()
    row = db.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not row:
        abort(404)
    media = db.execute("SELECT * FROM media WHERE recipe_id=? ORDER BY id", (recipe_id,)).fetchall()
    return render_template(
        "recipe.html",
        r=row,
        media=media,
        ingredients=split_lines(row["ingredients"]),
        steps=split_lines(row["steps"]),
        tags=[t for t in row["tags"].split(",") if t],
    )


@app.route("/recipes/<int:recipe_id>/edit", methods=["GET", "POST"])
def edit_recipe(recipe_id):
    db = get_db()
    row = db.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        data = recipe_from_form(request.form)
        if not data["title"]:
            flash("Give the recipe a title before saving.", "error")
            return render_template("recipe_form.html", recipe={**dict(row), **data, "id": recipe_id},
                                   mode="edit")
        data["cover_image"] = data["cover_image"] or row["cover_image"]
        data.update(updated_at=now(), id=recipe_id)
        db.execute(UPDATE_SQL, data)
        photos = attach_media(recipe_id, request.form, request.files)
        if photos and not data["cover_image"]:
            db.execute("UPDATE recipes SET cover_image=? WHERE id=?", (photos[0], recipe_id))
        db.commit()
        flash("Recipe saved.", "ok")
        return redirect(url_for("view_recipe", recipe_id=recipe_id))
    return render_template("recipe_form.html", recipe=dict(row), mode="edit")


@app.route("/recipes/<int:recipe_id>/delete", methods=["POST"])
def delete_recipe(recipe_id):
    db = get_db()
    for m in db.execute("SELECT filename FROM media WHERE recipe_id=? AND filename != ''",
                        (recipe_id,)).fetchall():
        remove_upload(m["filename"])
    db.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
    db.commit()
    flash("Recipe deleted.", "ok")
    return redirect(url_for("index"))


@app.route("/recipes/<int:recipe_id>/rating", methods=["POST"])
def set_rating(recipe_id):
    rating = to_int(request.form.get("rating"))
    rating = rating if rating in (1, 2, 3, 4, 5) else None
    db = get_db()
    db.execute("UPDATE recipes SET rating=?, updated_at=? WHERE id=?", (rating, now(), recipe_id))
    db.commit()
    return redirect(url_for("view_recipe", recipe_id=recipe_id))


@app.route("/media/<int:media_id>/cover", methods=["POST"])
def make_cover(media_id):
    db = get_db()
    m = db.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    if not m or m["kind"] != "image":
        abort(404)
    db.execute("UPDATE recipes SET cover_image=?, updated_at=? WHERE id=?",
               (m["filename"], now(), m["recipe_id"]))
    db.commit()
    flash("Cover photo updated.", "ok")
    return redirect(url_for("view_recipe", recipe_id=m["recipe_id"]))


@app.route("/media/<int:media_id>/delete", methods=["POST"])
def delete_media(media_id):
    db = get_db()
    m = db.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    if not m:
        abort(404)
    remove_upload(m["filename"])
    db.execute("DELETE FROM media WHERE id=?", (media_id,))
    if m["filename"]:
        db.execute("UPDATE recipes SET cover_image='' WHERE id=? AND cover_image=?",
                   (m["recipe_id"], m["filename"]))
    db.commit()
    return redirect(url_for("view_recipe", recipe_id=m["recipe_id"]))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- shopping list ----------

@app.route("/recipes/<int:recipe_id>/shopping", methods=["POST"])
def add_to_shopping(recipe_id):
    """Add checked ingredients. The same ingredient from several recipes stacks into one item."""
    db = get_db()
    recipe = db.execute("SELECT id, title FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not recipe:
        abort(404)
    added = 0
    skipped = 0
    stamp = now()
    for raw in request.form.getlist("items"):
        if not raw.strip():
            continue
        parsed = parse_ingredient(raw)
        if parsed["part"]:
            skipped += 1  # a sub-heading or a finished part of the recipe, not something to buy
            continue
        item = db.execute(
            "SELECT id FROM shopping_items WHERE checked=0 AND lower(name)=lower(?)",
            (parsed["name"],)).fetchone()
        if item:
            item_id = item["id"]
        else:
            item_id = db.execute(
                "INSERT INTO shopping_items (name, recipe_id, checked, created_at) VALUES (?, NULL, 0, ?)",
                (parsed["name"], stamp)).lastrowid
        already = db.execute(
            "SELECT 1 FROM shopping_lines WHERE item_id=? AND recipe_id=? AND text=?",
            (item_id, recipe_id, parsed["text"])).fetchone()
        if already:
            continue
        db.execute(
            """INSERT INTO shopping_lines (item_id, recipe_id, recipe_title, text, amount, grams, count,
               created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, recipe_id, recipe["title"], parsed["text"], parsed["amount"],
             parsed["grams"], parsed["count"], stamp))
        added += 1
    rebuild_items(db)
    db.commit()
    message = f"Added {added} item(s) to the shopping list." if added else "Those items are already on the list."
    if skipped:
        message += f" Skipped {skipped} sub-heading(s) or recipe part(s)."
    flash(message, "ok")
    return redirect(url_for("view_recipe", recipe_id=recipe_id))


def shopping_rows():
    """Each item with the amount to buy, and the recipes it comes from."""
    db = get_db()
    items = db.execute(
        """SELECT s.*, r.title AS recipe_title
           FROM shopping_items s LEFT JOIN recipes r ON r.id = s.recipe_id
           ORDER BY s.checked, s.created_at, s.id""").fetchall()
    lines_by_item = {}
    for line in db.execute("SELECT * FROM shopping_lines ORDER BY id"):
        lines_by_item.setdefault(line["item_id"], []).append(line)
    rows = []
    for it in items:
        lines = lines_by_item.get(it["id"], [])
        detail = None
        sources = []
        if lines:
            detail = purchase_text(item_key(it["name"].lower()), lines)
            if not detail:
                # No package rule for this ingredient: list what the recipes call for.
                detail = combined_amounts(it["name"], lines)
            sources = list(dict.fromkeys(
                (l["recipe_id"], l["recipe_title"]) for l in lines if l["recipe_id"]))
        elif it["recipe_id"]:
            sources = [(it["recipe_id"], it["recipe_title"] or "Recipe")]
        rows.append({"id": it["id"], "name": it["name"], "checked": it["checked"],
                     "detail": detail, "sources": sources, "check": not is_known_name(it["name"])})
    return rows


def refresh_shopping():
    """Bring every saved item in line with the current naming rules."""
    db = get_db()
    rebuild_items(db)
    db.commit()


def shopping_share_text(rows):
    """One item per line, for pasting into a text message (Walmart Text to Shop) or any app."""
    lines = []
    for row in rows:
        if row["checked"] or row["check"]:
            continue  # ticked items and unrecognised names are not sent to the store
        detail = row["detail"] or ""
        # "1 × 1 lb bag" -> "1 lb bag"; "2 × dozen" -> "2 dozen"
        detail = re.sub(r"^1 × ", "", detail)
        detail = re.sub(r"^(\d+) × ", r"\1 ", detail)
        if detail.startswith("Recipes call for") or detail.lower().startswith(row["name"].lower()):
            detail = ""
        lines.append(f"{row['name']}, {detail}" if detail else row["name"])
    return "\n".join(lines) + "\n"


@app.route("/shopping/share.txt")
def shopping_share():
    refresh_shopping()
    return Response(shopping_share_text(shopping_rows()), mimetype="text/plain; charset=utf-8")


@app.route("/shopping")
def shopping():
    refresh_shopping()
    rows = shopping_rows()
    return render_template("shopping.html",
                           items=[r for r in rows if not r["check"]],
                           check_items=[r for r in rows if r["check"]])


@app.route("/shopping/add", methods=["POST"])
def add_shopping_item():
    name = request.form.get("name", "").strip()
    if name:
        db = get_db()
        db.execute("INSERT INTO shopping_items (name, recipe_id, checked, created_at) VALUES (?, NULL, 0, ?)",
                   (name, now()))
        rebuild_items(db)
        db.commit()
    return redirect(url_for("shopping"))


@app.route("/shopping/<int:item_id>/toggle", methods=["POST"])
def toggle_shopping(item_id):
    db = get_db()
    db.execute("UPDATE shopping_items SET checked = 1 - checked WHERE id=?", (item_id,))
    db.commit()
    return redirect(url_for("shopping"))


@app.route("/shopping/<int:item_id>/delete", methods=["POST"])
def delete_shopping(item_id):
    db = get_db()
    db.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))
    db.commit()
    return redirect(url_for("shopping"))


@app.route("/shopping/clear-checked", methods=["POST"])
def clear_checked():
    db = get_db()
    db.execute("DELETE FROM shopping_items WHERE checked=1")
    db.commit()
    return redirect(url_for("shopping"))


@app.route("/shopping/clear-all", methods=["POST"])
def clear_all():
    db = get_db()
    db.execute("DELETE FROM shopping_items")
    db.commit()
    return redirect(url_for("shopping"))


# ---------- backup ----------

@app.route("/export.zip")
def export_zip():
    db = get_db()
    recipes = []
    for row in db.execute("SELECT * FROM recipes ORDER BY id").fetchall():
        item = dict(row)
        item["media"] = [dict(m) for m in db.execute(
            "SELECT * FROM media WHERE recipe_id=? ORDER BY id", (row["id"],)).fetchall()]
        recipes.append(item)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("recipes.json", json.dumps(recipes, indent=2, ensure_ascii=False))
        for name in os.listdir(UPLOAD_DIR):
            z.write(os.path.join(UPLOAD_DIR, name), f"uploads/{name}")
    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"recipe-keeper-backup-{stamp}.zip")


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", "5000")))
