"""Tests for shopping-list naming. Run from the project folder: python3 -m pytest -q tests"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from shopping import is_known_name, parse_ingredient, rebuild_items  # noqa: E402

# (recipe line, expected item name, expected to be recognised)
NAME_CASES = [
    ("2 cups all purpose flour, spooned and leveled", "All-purpose flour", True),
    ("2 cups all-purpose flour", "All-purpose flour", True),
    ("3 cups bread flour, sifted", "Bread flour", True),
    ("2 cups flour", "All-purpose flour", True),
    ("1 cup unsalted butter, softened to room temperature", "Unsalted butter", True),
    ("1 cup salted butter", "Salted butter", True),
    ("1 pkg (0.25 oz) active dry yeast", "Active dry yeast", True),
    ("2 1/4 tsp instant yeast", "Instant yeast", True),
    ("2 1/4 tsp yeast", "Yeast", False),
    ("1 lb spaghetti", "Spaghetti", True),
    ("1 lb penne, cooked and drained", "Penne", True),
    ("8 oz pasta", "Pasta", False),
    ("1 cup light or dark brown sugar, packed", "Brown sugar", True),
    ("1 cup brown sugar tightly packed", "Brown sugar", True),
    ("2 tbsp confectioners sugar if needed", "Confectioners sugar", True),
    ("1/2 cup confectioners sugar, if desired", "Confectioners sugar", True),
    ("2 eggs lightly beaten", "Eggs", True),
    ("1 egg", "Eggs", True),
    ("2 egg yolks", "Eggs", True),
    ("3 bananas, mashed", "Banana", True),
    ("1 tsp vanilla extract for serving", "Vanilla extract", True),
    ("2 cups flour for dusting", "All-purpose flour", True),
    ("1 cup cream cheese, softened", "Cream cheese", True),
    ("1 onion, finely chopped", "Onion", True),
    ("1 cup dried cranberries", "Dried cranberry", False),
    ("1/2 cup bread crumbs", "Bread crumb", True),
    ("1 tbsp mystery paste", "Mystery paste", False),
]


@pytest.mark.parametrize("line, name, known", NAME_CASES)
def test_item_name_and_known(line, name, known):
    parsed = parse_ingredient(line)
    assert parsed["name"] == name
    assert parsed["known"] is known


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE shopping_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            recipe_id INTEGER, checked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE shopping_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES shopping_items(id) ON DELETE CASCADE,
            recipe_id INTEGER, recipe_title TEXT NOT NULL DEFAULT '', text TEXT NOT NULL,
            amount TEXT NOT NULL DEFAULT '', grams REAL, count REAL, created_at TEXT NOT NULL);
    """)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def add_line(conn, name, text):
    item = conn.execute("INSERT INTO shopping_items (name, recipe_id, checked, created_at) VALUES (?, 1, 0, 'x')",
                        (name,)).lastrowid
    conn.execute("INSERT INTO shopping_lines (item_id, recipe_id, recipe_title, text, created_at) "
                 "VALUES (?, 1, 'Recipe', ?, 'x')", (item, text))
    return item


def items(conn):
    return [(r["name"], r["checked"]) for r in conn.execute("SELECT name, checked FROM shopping_items ORDER BY id")]


def test_saved_item_with_old_name_is_renamed():
    conn = make_db()
    add_line(conn, "Confectioner sugar if", "2 tbsp confectioners sugar if needed")
    rebuild_items(conn)
    assert items(conn) == [("Confectioners sugar", 0)]


def test_same_ingredient_from_two_recipes_merges():
    conn = make_db()
    add_line(conn, "Flour", "2 cups all purpose flour, spooned and leveled")
    add_line(conn, "All-purpose flour", "1 cup flour for dusting")
    rebuild_items(conn)
    assert items(conn) == [("All-purpose flour", 0)]
    lines = conn.execute("SELECT count(*) FROM shopping_lines").fetchone()[0]
    assert lines == 2


def test_different_flour_types_stay_separate():
    conn = make_db()
    add_line(conn, "Flour", "2 cups all purpose flour")
    add_line(conn, "Bread flour", "3 cups bread flour")
    rebuild_items(conn)
    assert sorted(items(conn)) == [("All-purpose flour", 0), ("Bread flour", 0)]


def test_eggs_from_recipe_and_yolk_roll_up():
    conn = make_db()
    add_line(conn, "Egg", "2 eggs")
    add_line(conn, "Egg yolk", "2 egg yolks")
    rebuild_items(conn)
    assert items(conn) == [("Eggs", 0)]


def test_ticked_and_unticked_stay_separate():
    conn = make_db()
    add_line(conn, "Flour", "1 cup flour")
    done = add_line(conn, "Flour", "1 cup flour")
    conn.execute("UPDATE shopping_items SET checked=1 WHERE id=?", (done,))
    rebuild_items(conn)
    assert sorted(items(conn)) == [("All-purpose flour", 0), ("All-purpose flour", 1)]


def test_typed_unknown_item_keeps_its_text():
    conn = make_db()
    conn.execute("INSERT INTO shopping_items (name, recipe_id, checked, created_at) VALUES ('Birthday candles', NULL, 0, 'x')")
    rebuild_items(conn)
    assert items(conn) == [("Birthday candles", 0)]


@pytest.mark.parametrize("line", [
    "Crust for 1 large pie:",
    "Filling for 1 large pie:",
    "For the crust",
    "Filling",
    "Crust",
])
def test_sub_headings_and_outcomes_are_parts(line):
    assert parse_ingredient(line)["part"] is True


@pytest.mark.parametrize("line", ["1 cup flour", "2 eggs", "1/4 tsp cloves", "1 onion, finely chopped"])
def test_real_ingredients_are_not_parts(line):
    assert parse_ingredient(line)["part"] is False


def test_ground_cloves_keep_their_name():
    parsed = parse_ingredient("¼ t. cloves")
    assert parsed["name"] == "Ground cloves"
    assert parsed["known"] is True


def test_part_lines_are_removed_when_rebuilding():
    conn = make_db()
    add_line(conn, "Crust for 1 large pie:", "Crust for 1 large pie:")
    add_line(conn, "Flour", "2 cups flour")
    rebuild_items(conn)
    assert items(conn) == [("All-purpose flour", 0)]


def test_known_name_lookup():
    assert is_known_name("Eggs")
    assert is_known_name("Confectioners sugar")
    assert not is_known_name("Confectioner sugar if")
