from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "food_cost.db"

app = Flask(__name__)

UNITS = [
    "pounds",
    "fluid ounces",
    "ounces",
    "milliliters",
    "liters",
    "quarts",
    "gallons",
    "each",
]

UNIT_FACTORS: Dict[str, Tuple[str, float]] = {
    "pounds": ("weight", 16.0),
    "ounces": ("weight", 1.0),
    "fluid ounces": ("volume", 29.5735),
    "milliliters": ("volume", 1.0),
    "liters": ("volume", 1000.0),
    "quarts": ("volume", 946.353),
    "gallons": ("volume", 3785.41),
    "each": ("count", 1.0),
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                ap_quantity REAL NOT NULL,
                ap_unit TEXT NOT NULL DEFAULT 'each',
                ap_price REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_name TEXT NOT NULL,
                portions REAL NOT NULL,
                spice_factor_percent REAL NOT NULL,
                total_cost REAL NOT NULL,
                cost_per_portion REAL NOT NULL,
                total_with_spice REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recipe_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL,
                ingredient_id INTEGER,
                ingredient_name TEXT NOT NULL,
                ep_quantity REAL NOT NULL,
                ep_unit TEXT NOT NULL,
                yield_percent REAL NOT NULL,
                ap_quantity REAL NOT NULL,
                ap_unit TEXT NOT NULL,
                ap_price REAL NOT NULL,
                ap_cost_per_unit REAL NOT NULL,
                ep_cost_per_unit REAL NOT NULL,
                extended_cost REAL NOT NULL,
                FOREIGN KEY(recipe_id) REFERENCES recipes(id),
                FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
            )
            """
        )


def to_currency(value: float) -> str:
    return f"${value:.2f}"


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float:
    if from_unit not in UNIT_FACTORS or to_unit not in UNIT_FACTORS:
        raise ValueError("Unsupported unit")

    from_group, from_factor = UNIT_FACTORS[from_unit]
    to_group, to_factor = UNIT_FACTORS[to_unit]

    if from_group != to_group:
        raise ValueError(
            f"Cannot convert {from_unit} to {to_unit}. Units must be from the same measurement type."
        )

    base_quantity = quantity * from_factor
    return base_quantity / to_factor


def parse_price(raw: str) -> float:
    return float(raw.replace("$", "").strip())


@app.route("/")
def index():
    return render_template("index.html", units=UNITS)


@app.post("/api/ingredients")
def add_ingredient():
    payload = request.get_json(force=True)
    name = payload["name"].strip()
    ap_quantity = float(payload["ap_quantity"])
    ap_unit = payload.get("ap_unit", "each")
    ap_price = parse_price(str(payload["ap_price"]))

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO ingredients (name, ap_quantity, ap_unit, ap_price, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                ap_quantity = excluded.ap_quantity,
                ap_unit = excluded.ap_unit,
                ap_price = excluded.ap_price
            """,
            (name, ap_quantity, ap_unit, ap_price, datetime.utcnow().isoformat()),
        )

    return jsonify({"message": "Ingredient saved."})


@app.get("/api/ingredients")
def ingredient_search():
    query = request.args.get("query", "").strip()
    if len(query) < 3:
        return jsonify([])

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, ap_quantity, ap_unit, ap_price
            FROM ingredients
            WHERE lower(name) LIKE lower(?)
            ORDER BY name ASC
            LIMIT 10
            """,
            (f"%{query}%",),
        ).fetchall()

    return jsonify(
        [
            {
                "id": row["id"],
                "name": row["name"],
                "ap_quantity": row["ap_quantity"],
                "ap_unit": row["ap_unit"],
                "ap_price": row["ap_price"],
                "ap_price_display": to_currency(row["ap_price"]),
            }
            for row in rows
        ]
    )


@app.post("/api/recipes")
def save_recipe():
    payload = request.get_json(force=True)
    recipe_name = payload["recipe_name"].strip()
    portions = float(payload["portions"])
    spice_factor_percent = float(payload["spice_factor_percent"])
    items = payload["items"]

    recipe_items = []
    total_cost = 0.0

    with get_connection() as conn:
        for item in items:
            ingredient_name = item["ingredient"].strip()
            ep_quantity = float(item["ep_quantity"])
            ep_unit = item.get("ep_unit", "each")
            yield_percent = float(item["yield_percent"])
            ap_quantity = float(item["ap_quantity"])
            ap_unit = item.get("ap_unit", "each")
            ap_price = parse_price(str(item["ap_price"]))

            existing = conn.execute(
                "SELECT id, ap_quantity, ap_unit, ap_price FROM ingredients WHERE lower(name) = lower(?)",
                (ingredient_name,),
            ).fetchone()

            if existing:
                ingredient_id = existing["id"]
                ap_quantity = float(existing["ap_quantity"])
                ap_unit = existing["ap_unit"]
                ap_price = float(existing["ap_price"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO ingredients (name, ap_quantity, ap_unit, ap_price, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        ingredient_name,
                        ap_quantity,
                        ap_unit,
                        ap_price,
                        datetime.utcnow().isoformat(),
                    ),
                )
                ingredient_id = cur.lastrowid

            converted_ap_qty_in_ep_units = convert_quantity(ap_quantity, ap_unit, ep_unit)
            ap_cost_per_unit = ap_price / converted_ap_qty_in_ep_units
            ep_cost_per_unit = ap_cost_per_unit / (yield_percent / 100.0)
            extended_cost = ep_cost_per_unit * ep_quantity
            total_cost += extended_cost

            recipe_items.append(
                {
                    "ingredient_id": ingredient_id,
                    "ingredient_name": ingredient_name,
                    "ep_quantity": ep_quantity,
                    "ep_unit": ep_unit,
                    "yield_percent": yield_percent,
                    "ap_quantity": ap_quantity,
                    "ap_unit": ap_unit,
                    "ap_price": ap_price,
                    "ap_cost_per_unit": ap_cost_per_unit,
                    "ep_cost_per_unit": ep_cost_per_unit,
                    "extended_cost": extended_cost,
                }
            )

        cost_per_portion = total_cost / portions
        spice_factor = spice_factor_percent / 100.0
        total_with_spice = (cost_per_portion * spice_factor) + cost_per_portion

        recipe_cursor = conn.execute(
            """
            INSERT INTO recipes (
                recipe_name,
                portions,
                spice_factor_percent,
                total_cost,
                cost_per_portion,
                total_with_spice,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe_name,
                portions,
                spice_factor_percent,
                total_cost,
                cost_per_portion,
                total_with_spice,
                datetime.utcnow().isoformat(),
            ),
        )
        recipe_id = recipe_cursor.lastrowid

        conn.executemany(
            """
            INSERT INTO recipe_items (
                recipe_id,
                ingredient_id,
                ingredient_name,
                ep_quantity,
                ep_unit,
                yield_percent,
                ap_quantity,
                ap_unit,
                ap_price,
                ap_cost_per_unit,
                ep_cost_per_unit,
                extended_cost
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    recipe_id,
                    item["ingredient_id"],
                    item["ingredient_name"],
                    item["ep_quantity"],
                    item["ep_unit"],
                    item["yield_percent"],
                    item["ap_quantity"],
                    item["ap_unit"],
                    item["ap_price"],
                    item["ap_cost_per_unit"],
                    item["ep_cost_per_unit"],
                    item["extended_cost"],
                )
                for item in recipe_items
            ],
        )

    return jsonify(
        {
            "recipe_id": recipe_id,
            "total_cost": to_currency(total_cost),
            "cost_per_portion": to_currency(cost_per_portion),
            "total_with_spice": to_currency(total_with_spice),
        }
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
