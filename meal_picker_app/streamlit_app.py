from __future__ import annotations

import csv
import io
import json
import random
import re
import zipfile
from datetime import date, time, timedelta
from html import escape
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = APP_DIR / "meal_data.json"
SETTINGS_PATH = APP_DIR / "meal_settings.json"
MEDIA_DIR = APP_DIR / "meal_media"
SCHEDULE_PATH = APP_DIR / "saved_schedule.json"

DAY_PARTS = ["Breakfast", "Lunch", "Dinner"]
BASE_MEAL_FIELDS = [
    "description",
    "category",
    "preference",
    "time",
    "cost",
    "fill",
    "ingredients",
    "directions",
    "meal_photos",
    "ingredient_photos",
    "step_photos",
]
CATEGORY_MAP = {
    "Breakfast": {"Breakfast", "Breakfast/Lunch", "Breakfast/Lunch/Dinner"},
    "Lunch": {"Lunch", "Breakfast/Lunch", "Lunch/Dinner", "Breakfast/Lunch/Dinner"},
    "Dinner": {"Dinner", "Lunch/Dinner", "Breakfast/Lunch/Dinner"},
}
SLOT_TIMES = {
    "Breakfast": (time(5, 0), time(7, 0)),
    "Lunch": (time(11, 0), time(13, 0)),
    "Dinner": (time(17, 0), time(18, 0)),
}

PREFERENCE_OPTIONS = ["", "Low", "Medium", "High"]
TIME_OPTIONS = ["", "Low", "Medium", "High"]
COST_OPTIONS = ["", "$", "$$", "$$$"]
FILL_OPTIONS = ["", "Complete", "Needs Starch", "Needs Vegitable"]
CATEGORY_OPTIONS = [
    "Breakfast",
    "Lunch",
    "Dinner",
    "Breakfast/Lunch",
    "Lunch/Dinner",
    "Breakfast/Lunch/Dinner",
]


STANDARD_UNITS = [
    "",
    "tsp", "tbsp", "cup",
    "ml", "l",
    "g", "kg",
    "oz", "lb",
    "pinch", "dash",
    "clove", "slice",
    "can", "package",
    "piece",
]

UNIT_ALIASES = {
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "cups": "cup",
    "grams": "g",
    "gram": "g",
    "kilograms": "kg",
    "kilogram": "kg",
    "ounces": "oz",
    "ounce": "oz",
    "lbs": "lb",
    "pounds": "lb",
    "pound": "lb",
    "cloves": "clove",
    "slices": "slice",
    "cans": "can",
    "packages": "package",
    "pkg": "package",
    "pkgs": "package",
    "pieces": "piece",
}


def normalize_unit(unit: str) -> str:
    cleaned = (unit or "").strip().lower().rstrip(".")
    return UNIT_ALIASES.get(cleaned, cleaned)


def normalize_ingredient_entry(raw_ingredient) -> dict:
    if isinstance(raw_ingredient, dict):
        qty = raw_ingredient.get("qty")
        unit = normalize_unit(str(raw_ingredient.get("unit", "")))
        name = str(raw_ingredient.get("name", "")).strip()
    else:
        qty, unit, name = parse_ingredient_amount_text(str(raw_ingredient or ""))
        unit = normalize_unit(unit)
        name = name.strip()
    try:
        qty = float(qty) if qty not in (None, "") else None
    except Exception:
        qty = None
    return {"qty": qty, "unit": unit, "name": name}


def ingredient_entries(value) -> List[dict]:
    if isinstance(value, dict):
        value = value.get("ingredients", [])
    if not isinstance(value, list):
        value = [value] if value else []
    entries: List[dict] = []
    for item in value:
        entry = normalize_ingredient_entry(item)
        if entry.get("name"):
            entries.append(entry)
    return entries


def format_ingredient(ingredient: dict | str) -> str:
    entry = normalize_ingredient_entry(ingredient)
    qty = format_scaled_quantity(entry["qty"]) if entry.get("qty") not in (None, "") else ""
    unit = entry.get("unit", "")
    name = entry.get("name", "")
    return " ".join(part for part in [qty, unit, name] if part).strip()


def ingredient_name_text(ingredient: dict | str) -> str:
    return normalize_ingredient_entry(ingredient).get("name", "")


def ingredient_photo_key(ingredient: dict | str) -> str:
    return format_ingredient(ingredient) or ingredient_name_text(ingredient)


def ingredient_qty_value(ingredient: dict | str, default: float = 0.0) -> float:
    qty = normalize_ingredient_entry(ingredient).get("qty")
    return float(qty) if qty not in (None, "") else float(default)


def ingredient_unit_value(ingredient: dict | str) -> str:
    return normalize_ingredient_entry(ingredient).get("unit", "")


def ingredient_name_value(ingredient: dict | str) -> str:
    return normalize_ingredient_entry(ingredient).get("name", "")


def ingredient_display_list(ingredients) -> List[str]:
    return [format_ingredient(entry) for entry in ingredient_entries(ingredients) if format_ingredient(entry)]


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


@st.cache_data
def load_meals() -> List[dict]:
    data = _read_json(DATA_PATH, [])
    meals = data if isinstance(data, list) else []
    normalized: List[dict] = []
    for meal in meals:
        if not isinstance(meal, dict):
            continue
        meal = dict(meal)
        meal.setdefault("description", "")
        meal.setdefault("category", "")
        meal.setdefault("preference", "")
        meal.setdefault("time", "")
        meal.setdefault("cost", "")
        meal.setdefault("fill", "")
        meal.setdefault("ingredients", [])
        meal.setdefault("directions", "")
        meal.setdefault("meal_photos", [])
        meal.setdefault("ingredient_photos", {})
        meal.setdefault("step_photos", {})
        if not isinstance(meal["ingredients"], list):
            meal["ingredients"] = [meal["ingredients"]] if meal["ingredients"] else []
        meal["ingredients"] = ingredient_entries(meal.get("ingredients", []))
        if not isinstance(meal["meal_photos"], list):
            meal["meal_photos"] = []
        if not isinstance(meal["ingredient_photos"], dict):
            meal["ingredient_photos"] = {}
        if not isinstance(meal["step_photos"], dict):
            meal["step_photos"] = {}
        meal["ingredient_photos"] = {
            str(key): [str(item) for item in value if item]
            for key, value in meal["ingredient_photos"].items()
            if isinstance(value, list)
        }
        meal["step_photos"] = {
            str(key): [str(item) for item in value if item]
            for key, value in meal["step_photos"].items()
            if isinstance(value, list)
        }
        normalized.append(meal)
    return normalized


def save_meals(meals: List[dict]) -> None:
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(meals, f, indent=2)
    st.cache_data.clear()


@st.cache_data
def meal_lookup() -> Dict[str, dict]:
    return {meal["description"]: meal for meal in load_meals() if meal.get("description")}


@st.cache_data
def custom_columns() -> List[str]:
    extras = set()
    for meal in load_meals():
        for key in meal:
            if key not in BASE_MEAL_FIELDS:
                extras.add(key)
    return sorted(extras, key=str.lower)


@st.cache_data
def meal_table() -> pd.DataFrame:
    rows = []
    extras = custom_columns()
    for meal in load_meals():
        row = {
            "Meal": meal.get("description", ""),
            "Category": meal.get("category", ""),
            "Preference": meal.get("preference", ""),
            "Time": meal.get("time", ""),
            "Cost": meal.get("cost", ""),
            "Fill": meal.get("fill", ""),
            "Ingredients": ", ".join(ingredient_display_list(meal.get("ingredients", []))),
            "Directions": meal.get("directions", ""),
            "Meal Photos": len(meal.get("meal_photos", [])),
            "Ingredient Photos": sum(len(v) for v in (meal.get("ingredient_photos", {}) or {}).values()),
            "Step Photos": sum(len(v) for v in (meal.get("step_photos", {}) or {}).values()),
        }
        for extra in extras:
            value = meal.get(extra, "")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            row[extra.replace("_", " ").title()] = value
        rows.append(row)
    return pd.DataFrame(rows)


@st.cache_data
def unique_values(field: str) -> List[str]:
    return sorted({meal.get(field, "") for meal in load_meals() if meal.get(field)})


@st.cache_data
def load_settings() -> dict:
    data = _read_json(SETTINGS_PATH, {})
    if not isinstance(data, dict):
        data = {}
    return {
        "include_standard_weekly": bool(data.get("include_standard_weekly", False)),
        "standard_weekly_items": str(data.get("standard_weekly_items", "")),
    }


def save_settings(include_standard_weekly: bool, standard_weekly_items: str) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "include_standard_weekly": bool(include_standard_weekly),
                "standard_weekly_items": standard_weekly_items.strip(),
            },
            f,
            indent=2,
        )
    st.cache_data.clear()


def load_saved_schedule() -> dict:
    data = _read_json(SCHEDULE_PATH, {})
    if not isinstance(data, dict):
        data = {}
    slots = data.get("slots", {})
    if not isinstance(slots, dict):
        slots = {}
    cleaned_slots = {str(key): str(value) for key, value in slots.items() if isinstance(key, str)}
    offset_days = data.get("offset_days", 0)
    try:
        offset_days = int(offset_days)
    except Exception:
        offset_days = 0
    num_days = data.get("num_days", 7)
    try:
        num_days = int(num_days)
    except Exception:
        num_days = 7
    num_days = max(1, min(31, num_days))
    return {"offset_days": max(0, min(365, offset_days)), "num_days": num_days, "slots": cleaned_slots}


def apply_saved_schedule_to_session() -> None:
    schedule = load_saved_schedule()
    for i in range(31):
        for part in DAY_PARTS:
            st.session_state.setdefault(slot_key(i, part), schedule["slots"].get(slot_key(i, part), "--"))
    st.session_state.setdefault("offset_days", schedule.get("offset_days", 0))
    st.session_state.setdefault("num_days", schedule.get("num_days", 7))


def save_current_schedule() -> None:
    num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
    payload = {
        "offset_days": int(st.session_state.get("offset_days", 0)),
        "num_days": num_days,
        "slots": {slot_key(i, part): st.session_state.get(slot_key(i, part), "--") for i in range(31) for part in DAY_PARTS},
    }
    with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def safe_close_down() -> None:
    save_current_schedule()
    save_settings(
        bool(st.session_state.get("include_standard_weekly", False)),
        str(st.session_state.get("standard_weekly_items", "")),
    )
    st.session_state["safe_close_requested"] = True


def slugify_for_path(text_value: str) -> str:
    cleaned = sanitize_column_key(text_value)
    return cleaned or "item"


def meal_media_paths(relative_paths: List[str]) -> List[str]:
    return [str((APP_DIR / rel).resolve()) for rel in relative_paths if rel]


def persist_uploaded_images(meal_name: str, bucket: str, files, label: str = "") -> List[str]:
    if not files:
        return []
    files = [file for file in files if file is not None]
    if not files:
        return []
    meal_dir = MEDIA_DIR / slugify_for_path(meal_name) / slugify_for_path(bucket)
    if label:
        meal_dir = meal_dir / slugify_for_path(label)
    meal_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: List[str] = []
    existing_names = {path.name for path in meal_dir.glob("*") if path.is_file()}
    next_index = len(existing_names) + 1
    for uploaded in files:
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        file_name = f"{slugify_for_path(label or bucket)}_{next_index:02d}{suffix}"
        while file_name in existing_names:
            next_index += 1
            file_name = f"{slugify_for_path(label or bucket)}_{next_index:02d}{suffix}"
        target = meal_dir / file_name
        target.write_bytes(uploaded.getbuffer())
        saved_paths.append(str(target.relative_to(APP_DIR)).replace("\\", "/"))
        existing_names.add(file_name)
        next_index += 1
    return saved_paths


def merge_media_lists(existing: List[str], new_items: List[str]) -> List[str]:
    merged: List[str] = []
    for item in list(existing) + list(new_items):
        if item and item not in merged:
            merged.append(item)
    return merged


def normalize_meal_record(meal: dict) -> dict:
    meal = dict(meal or {})
    meal.setdefault("description", "")
    meal.setdefault("category", "")
    meal.setdefault("preference", "")
    meal.setdefault("time", "")
    meal.setdefault("cost", "")
    meal.setdefault("fill", "")
    meal.setdefault("ingredients", [])
    meal.setdefault("directions", "")
    meal.setdefault("meal_photos", [])
    meal.setdefault("ingredient_photos", {})
    meal.setdefault("step_photos", {})
    if not isinstance(meal["ingredients"], list):
        meal["ingredients"] = [meal["ingredients"]] if meal["ingredients"] else []
    meal["ingredients"] = ingredient_entries(meal.get("ingredients", []))
    if not isinstance(meal["meal_photos"], list):
        meal["meal_photos"] = []
    if not isinstance(meal["ingredient_photos"], dict):
        meal["ingredient_photos"] = {}
    if not isinstance(meal["step_photos"], dict):
        meal["step_photos"] = {}
    meal["ingredient_photos"] = {
        str(key): [str(item) for item in value if item]
        for key, value in meal["ingredient_photos"].items()
        if isinstance(value, list)
    }
    meal["step_photos"] = {
        str(key): [str(item) for item in value if item]
        for key, value in meal["step_photos"].items()
        if isinstance(value, list)
    }
    return meal


def meal_media_relpaths(meal: dict) -> List[str]:
    relpaths: List[str] = []
    for rel_path in meal.get("meal_photos", []) or []:
        if rel_path and rel_path not in relpaths:
            relpaths.append(str(rel_path).replace("\\", "/"))
    for photo_map_key in ("ingredient_photos", "step_photos"):
        photo_map = meal.get(photo_map_key, {}) or {}
        if not isinstance(photo_map, dict):
            continue
        for values in photo_map.values():
            if not isinstance(values, list):
                continue
            for rel_path in values:
                if rel_path and rel_path not in relpaths:
                    relpaths.append(str(rel_path).replace("\\", "/"))
    return relpaths


def build_meal_export_bundle(selected_names: List[str]) -> bytes:
    meals = []
    selected = {name.strip() for name in selected_names if name and name.strip()}
    for meal in load_meals():
        meal_name = str(meal.get("description", "")).strip()
        if meal_name and meal_name in selected:
            meals.append(meal)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "meals.json",
            json.dumps({"format": "ump_meal_bundle_v1", "meals": meals}, indent=2).encode("utf-8"),
        )
        added_paths = set()
        for meal in meals:
            for rel_path in meal_media_relpaths(meal):
                normalized_rel = rel_path.replace("\\", "/").lstrip("/")
                if not normalized_rel or normalized_rel in added_paths:
                    continue
                abs_path = (APP_DIR / normalized_rel).resolve()
                try:
                    abs_path.relative_to(APP_DIR.resolve())
                except ValueError:
                    continue
                if abs_path.exists() and abs_path.is_file():
                    bundle.write(abs_path, arcname=normalized_rel)
                    added_paths.add(normalized_rel)
    buffer.seek(0)
    return buffer.getvalue()


def _safe_extract_bundle_media(bundle: zipfile.ZipFile, meals: List[dict]) -> None:
    app_root = APP_DIR.resolve()
    names = set(bundle.namelist())
    for meal in meals:
        for rel_path in meal_media_relpaths(meal):
            normalized_rel = rel_path.replace("\\", "/").lstrip("/")
            if not normalized_rel or normalized_rel not in names:
                continue
            target_path = (APP_DIR / normalized_rel).resolve()
            try:
                target_path.relative_to(app_root)
            except ValueError:
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(normalized_rel) as src, open(target_path, "wb") as dst:
                dst.write(src.read())


def import_meal_files(files, duplicate_mode: str = "skip") -> tuple[int, int, int, List[str]]:
    existing_meals = load_meals()
    existing_by_name = {str(meal.get("description", "")).strip(): dict(meal) for meal in existing_meals if str(meal.get("description", "")).strip()}
    added = 0
    replaced = 0
    skipped = 0
    errors: List[str] = []

    for uploaded in files or []:
        if uploaded is None:
            continue
        try:
            raw_bytes = uploaded.getvalue()
            suffix = Path(uploaded.name).suffix.lower()
            imported_meals: List[dict] = []

            if suffix == ".zip":
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as bundle:
                    manifest_name = "meals.json" if "meals.json" in bundle.namelist() else next((name for name in bundle.namelist() if name.lower().endswith('.json')), None)
                    if not manifest_name:
                        raise ValueError("No meals.json file was found in the zip bundle.")
                    payload = json.loads(bundle.read(manifest_name).decode("utf-8"))
                    if isinstance(payload, dict) and isinstance(payload.get("meals"), list):
                        imported_meals = [normalize_meal_record(item) for item in payload.get("meals", []) if isinstance(item, dict)]
                    elif isinstance(payload, list):
                        imported_meals = [normalize_meal_record(item) for item in payload if isinstance(item, dict)]
                    elif isinstance(payload, dict):
                        imported_meals = [normalize_meal_record(payload)]
                    else:
                        raise ValueError("The zip bundle does not contain meal data in a supported format.")
                    _safe_extract_bundle_media(bundle, imported_meals)
            elif suffix == ".json":
                payload = json.loads(raw_bytes.decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("meals"), list):
                    imported_meals = [normalize_meal_record(item) for item in payload.get("meals", []) if isinstance(item, dict)]
                elif isinstance(payload, list):
                    imported_meals = [normalize_meal_record(item) for item in payload if isinstance(item, dict)]
                elif isinstance(payload, dict):
                    imported_meals = [normalize_meal_record(payload)]
                else:
                    raise ValueError("The JSON file does not contain meal data in a supported format.")
            else:
                raise ValueError("Use a .zip bundle exported by this app or a .json meal file.")

            for meal in imported_meals:
                meal_name = str(meal.get("description", "")).strip()
                if not meal_name:
                    skipped += 1
                    continue
                if meal_name in existing_by_name:
                    if duplicate_mode == "replace":
                        existing_by_name[meal_name] = meal
                        replaced += 1
                    else:
                        skipped += 1
                else:
                    existing_by_name[meal_name] = meal
                    added += 1
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")

    merged_meals = sorted(existing_by_name.values(), key=lambda meal: str(meal.get("description", "")).lower())
    if added or replaced:
        save_meals(merged_meals)
    return added, replaced, skipped, errors


def finalize_meal_with_media(meal_payload: dict, form_media: dict, existing_meal: dict | None = None) -> dict:
    existing_meal = existing_meal or {}
    finalized = dict(meal_payload)
    meal_name = finalized.get("description", "").strip()

    existing_meal_photos = list(existing_meal.get("meal_photos", []))
    new_meal_photos = persist_uploaded_images(meal_name, "meal_photos", form_media.get("meal_photo_files", []), label="meal")
    finalized["meal_photos"] = merge_media_lists(existing_meal_photos, new_meal_photos)

    ingredient_uploads = form_media.get("ingredient_photo_files", {})
    existing_ingredient_photos = existing_meal.get("ingredient_photos", {}) if isinstance(existing_meal.get("ingredient_photos", {}), dict) else {}
    finalized_ingredient_photos = {}
    for ingredient in finalized.get("ingredients", []):
        ingredient_key = ingredient_photo_key(ingredient)
        existing_paths = list(existing_ingredient_photos.get(ingredient_key, []))
        new_paths = persist_uploaded_images(meal_name, "ingredient_photos", ingredient_uploads.get(ingredient_key, []), label=ingredient_key)
        merged = merge_media_lists(existing_paths, new_paths)
        if merged:
            finalized_ingredient_photos[ingredient_key] = merged
    finalized["ingredient_photos"] = finalized_ingredient_photos

    steps = parse_direction_steps(finalized.get("directions", ""))
    step_uploads = form_media.get("step_photo_files", {})
    existing_step_photos = existing_meal.get("step_photos", {}) if isinstance(existing_meal.get("step_photos", {}), dict) else {}
    finalized_step_photos = {}
    for step_index, _step_text in enumerate(steps):
        step_key = str(step_index)
        existing_paths = list(existing_step_photos.get(step_key, []))
        new_paths = persist_uploaded_images(meal_name, "step_photos", step_uploads.get(step_key, []), label=f"step_{step_index + 1}")
        merged = merge_media_lists(existing_paths, new_paths)
        if merged:
            finalized_step_photos[step_key] = merged
    finalized["step_photos"] = finalized_step_photos
    return finalized


def parse_standard_weekly_items(raw_text: str) -> List[str]:
    items: List[str] = []
    for line in raw_text.replace(",", "\n").splitlines():
        item = line.strip()
        if item:
            items.append(item)
    return items


def sanitize_column_key(raw_name: str) -> str:
    cleaned = "_".join(raw_name.strip().lower().split())
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_")


def filters_match(meal: dict, prefs: List[str], times: List[str], costs: List[str], fills: List[str]) -> bool:
    base_match = (
        (not prefs or meal.get("preference", "") in prefs)
        and (not times or meal.get("time", "") in times)
        and (not costs or meal.get("cost", "") in costs)
        and (not fills or meal.get("fill", "") in fills)
    )
    if not base_match:
        return False

    for extra in custom_columns():
        selected_values = [str(value).strip() for value in st.session_state.get(f"meal_filter_custom_{extra}", []) if str(value).strip()]
        if not selected_values:
            continue
        meal_value = str(meal.get(extra, "")).strip()
        if meal_value not in selected_values:
            return False
    return True


def meal_options(day_part: str, prefs: List[str], times: List[str], costs: List[str], fills: List[str]) -> List[str]:
    options = []
    for meal in load_meals():
        if meal.get("category") in CATEGORY_MAP[day_part] and filters_match(meal, prefs, times, costs, fills):
            desc = meal.get("description", "").strip()
            if desc:
                options.append(desc)
    return ["--"] + sorted(set(options), key=str.lower)


def add_custom_column(raw_name: str) -> tuple[bool, str]:
    key = sanitize_column_key(raw_name)
    if not key:
        return False, "Enter a column name first."
    if key in BASE_MEAL_FIELDS:
        return False, "That column already exists as a built-in field."

    meals = load_meals()
    existing_keys = set(BASE_MEAL_FIELDS)
    for meal in meals:
        existing_keys.update(meal.keys())
    if key in existing_keys:
        return False, "That column already exists."

    for meal in meals:
        meal[key] = ""
    save_meals(meals)
    return True, f"Added column '{raw_name.strip()}'."


def delete_meal_by_name(meal_name: str) -> tuple[bool, str]:
    meal_name = meal_name.strip()
    if not meal_name:
        return False, "Choose a meal to delete."
    meals = load_meals()
    filtered = [meal for meal in meals if meal.get("description", "") != meal_name]
    if len(filtered) == len(meals):
        return False, "Meal not found."
    save_meals(filtered)
    return True, f"Deleted '{meal_name}'."


def update_meal(original_name: str, updated_meal: dict) -> tuple[bool, str]:
    original_name = original_name.strip()
    new_name = updated_meal.get("description", "").strip()
    if not original_name:
        return False, "Choose a meal to edit."
    if not new_name:
        return False, "Meal name is required."

    meals = load_meals()
    original_index = next((idx for idx, meal in enumerate(meals) if meal.get("description", "") == original_name), None)
    if original_index is None:
        return False, "Meal not found."

    duplicate_index = next(
        (idx for idx, meal in enumerate(meals) if meal.get("description", "") == new_name and idx != original_index),
        None,
    )
    if duplicate_index is not None:
        return False, "Another meal already uses that name."

    meals[original_index] = updated_meal
    save_meals(meals)
    return True, f"Updated '{new_name}'."


def slot_key(day_index: int, day_part: str) -> str:
    return f"slot_{day_index}_{day_part.lower()}"


def ensure_slot_defaults() -> None:
    for i in range(31):
        for part in DAY_PARTS:
            st.session_state.setdefault(slot_key(i, part), "--")


def selected_meals() -> List[dict]:
    lookup = meal_lookup()
    chosen = []
    for i in range(31):
        for part in DAY_PARTS:
            meal_name = st.session_state.get(slot_key(i, part), "--")
            if meal_name and meal_name != "--" and meal_name in lookup:
                chosen.append(lookup[meal_name])
    return chosen


def clear_schedule() -> None:
    for i in range(31):
        for part in DAY_PARTS:
            st.session_state[slot_key(i, part)] = "--"


def auto_fill_blanks(day_part: str, options: List[str]) -> None:
    candidates = [name for name in options if name != "--"]
    if not candidates:
        return

    num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
    blank_slots = [i for i in range(num_days) if st.session_state.get(slot_key(i, day_part), "--") == "--"]
    if not blank_slots:
        return

    used_all = {
        st.session_state.get(slot_key(i, part), "--")
        for i in range(num_days)
        for part in DAY_PARTS
    }
    used_all.discard("--")
    unused_candidates = [name for name in candidates if name not in used_all]
    random.shuffle(unused_candidates)

    for idx in blank_slots:
        if unused_candidates:
            pick = unused_candidates.pop(0)
        else:
            used_for_part = {
                st.session_state.get(slot_key(i, day_part), "--")
                for i in range(7)
            }
            used_for_part.discard("--")
            part_unused = [name for name in candidates if name not in used_for_part]
            pick = random.choice(part_unused if part_unused else candidates)
        st.session_state[slot_key(idx, day_part)] = pick
        used_all.add(pick)


def auto_fill_all_blanks(breakfast_options: List[str], lunch_options: List[str], dinner_options: List[str]) -> None:
    auto_fill_blanks("Breakfast", breakfast_options)
    auto_fill_blanks("Lunch", lunch_options)
    auto_fill_blanks("Dinner", dinner_options)


def add_random_meal_to_random_day(day_part: str, options: List[str]) -> None:
    candidates = [name for name in options if name != "--"]
    if not candidates:
        return
    num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
    blank_slots = [i for i in range(num_days) if st.session_state.get(slot_key(i, day_part), "--") == "--"]
    if not blank_slots:
        return
    used_for_part = {st.session_state.get(slot_key(i, day_part), "--") for i in range(num_days)}
    used_for_part.discard("--")
    unused_candidates = [name for name in candidates if name not in used_for_part]
    pick = random.choice(unused_candidates if unused_candidates else candidates)
    target_day = random.choice(blank_slots)
    st.session_state[slot_key(target_day, day_part)] = pick


def grocery_items(meals: List[dict], include_standard_weekly: bool = False, standard_weekly_items: str = "") -> List[str]:
    combined: dict[tuple[str, str], dict] = {}
    for meal in meals:
        for ingredient in ingredient_entries(meal.get("ingredients", [])):
            name = ingredient.get("name", "").strip()
            if not name:
                continue
            unit = normalize_unit(ingredient.get("unit", ""))
            key = (normalize_ingredient_name(ingredient), unit)
            entry = combined.setdefault(key, {"qty": 0.0, "has_qty": False, "unit": unit, "name": name})
            qty = ingredient.get("qty")
            if qty not in (None, ""):
                entry["qty"] += float(qty)
                entry["has_qty"] = True
    items = [
        f"{format_scaled_quantity(item['qty'])} {item['unit']} {item['name']}".strip() if item['has_qty'] else item['name']
        for item in sorted(combined.values(), key=lambda value: value['name'].lower())
    ]
    if include_standard_weekly:
        items.extend(parse_standard_weekly_items(standard_weekly_items))
    return sorted({item.strip() for item in items if item and item.strip()}, key=str.lower)


def filtered_display_ingredients(ingredients) -> List[str]:
    hidden_values = {"-eat out", "-leftovers"}
    return [
        item.strip()
        for item in ingredient_display_list(ingredients)
        if item and item.strip() and item.strip().lower() not in hidden_values
    ]


def csv_bytes_for_meals(start_day: date, dinner_only: bool = False) -> bytes:
    rows = []
    num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
    for i in range(num_days):
        day_date = start_day + timedelta(days=i)
        for day_part in DAY_PARTS:
            if dinner_only and day_part != "Dinner":
                continue
            meal_name = st.session_state.get(slot_key(i, day_part), "--")
            if meal_name == "--":
                continue
            start_t, end_t = SLOT_TIMES[day_part]
            rows.append(
                {
                    "Subject": meal_name,
                    "Start date": day_date.isoformat(),
                    "End date": day_date.isoformat(),
                    "Start Time": start_t.strftime("%H:%M"),
                    "End Time": end_t.strftime("%H:%M"),
                    "All Day Event": False,
                    "Description": day_part,
                }
            )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "Subject",
            "Start date",
            "End date",
            "Start Time",
            "End Time",
            "All Day Event",
            "Description",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def weekly_plan_rows(start_day: date) -> List[dict]:
    lookup = meal_lookup()
    rows: List[dict] = []
    num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
    for i in range(num_days):
        day_date = start_day + timedelta(days=i)
        day_meals = []
        for part in DAY_PARTS:
            meal_name = st.session_state.get(slot_key(i, part), "--")
            meal = lookup.get(meal_name) if meal_name and meal_name != "--" else None
            day_meals.append(
                {
                    "day_part": part,
                    "name": meal_name if meal_name and meal_name != "--" else "—",
                    "ingredients": ingredient_display_list((meal or {}).get("ingredients", [])),
                    "directions": (meal or {}).get("directions", "").strip(),
                }
            )
        rows.append({"date": day_date, "meals": day_meals})
    return rows


def weekly_plan_html(start_day: date, title: str = "Weekly Meal Plan") -> str:
    rows = weekly_plan_rows(start_day)
    cards_html: List[str] = []
    for row in rows:
        meal_blocks: List[str] = []
        for meal in row["meals"]:
            ingredients_html = ""
            if meal["ingredients"]:
                ingredients_html = (
                    '<div class="ingredients"><strong>Ingredients:</strong> '
                    + escape(", ".join(meal["ingredients"]))
                    + "</div>"
                )
            directions_html = ""
            if meal["directions"]:
                directions_html = (
                    '<div class="directions"><strong>Directions:</strong> '
                    + escape(meal["directions"])
                    + "</div>"
                )
            meal_blocks.append(
                f'''<div class="meal-block">
                    <div class="meal-head">
                        <span class="meal-part">{escape(meal["day_part"])}</span>
                        <span class="meal-name">{escape(meal["name"])}</span>
                    </div>
                    {ingredients_html}
                    {directions_html}
                </div>'''
            )
        cards_html.append(
            f'''<section class="day-card">
                <div class="day-topbar"></div>
                <div class="day-title-row">
                    <div class="day-name">{escape(row["date"].strftime("%A"))}</div>
                    <div class="day-date">{escape(row["date"].strftime("%B %d, %Y"))}</div>
                </div>
                {''.join(meal_blocks)}
            </section>'''
        )

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
    @page {{ size: 8.5in 11in; margin: 0.45in; }}
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        font-family: Inter, "Segoe UI", Arial, sans-serif;
        color: #1f2937;
        background: #f4f1ea;
    }}
    .page {{
        width: 7.6in;
        min-height: 10.1in;
        margin: 0 auto;
        background: linear-gradient(180deg, #fffdf9 0%, #f8f5ee 100%);
        border: 1px solid #e8decf;
        border-radius: 20px;
        padding: 0.32in;
        box-shadow: 0 16px 40px rgba(58, 42, 24, 0.12);
    }}
    .hero {{
        display: flex;
        justify-content: space-between;
        align-items: end;
        margin-bottom: 0.18in;
        padding-bottom: 0.16in;
        border-bottom: 2px solid #eadfce;
    }}
    .hero h1 {{
        margin: 0;
        font-size: 24px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #3f2d1f;
    }}
    .hero .subtitle {{
        margin-top: 6px;
        color: #7a6a58;
        font-size: 12px;
    }}
    .badge {{
        padding: 8px 14px;
        border-radius: 999px;
        background: linear-gradient(135deg, #8b5e34, #c89c6d);
        color: white;
        font-weight: 700;
        font-size: 11px;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }}
    .grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.18in;
    }}
    .day-card {{
        break-inside: avoid;
        background: white;
        border: 3px solid #efe4d6;
        border-radius: 18px;
        overflow: hidden;
        box-shadow: 0 10px 24px rgba(98, 73, 45, 0.08);
    }}
    .day-topbar {{
        height: 10px;
        background: #0b3d91;  /* solid dark blue */
    }}
    .day-title-row {{ padding: 14px 16px 8px 16px; }}
    .day-name {{ font-size: 20px; font-weight: 800; color: #2f241a; }}
    .day-date {{ font-size: 12px; color: #887663; margin-top: 2px; }}
    .meal-block {{
        margin: 0 12px 12px 12px;
        padding: 12px 12px 10px 12px;
        border-radius: 14px;
        background: linear-gradient(180deg, #fffdfa 0%, #fbf7f1 100%);
        border: 1px solid #efe2d3;
    }}
    .meal-head {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: baseline;
        margin-bottom: 6px;
    }}
    .meal-part {{
        font-size: 11px;
        font-weight: 800;
        color: #9d6d3c;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        min-width: 78px;
    }}
    .meal-name {{
        flex: 1;
        font-size: 15px;
        font-weight: 700;
        color: #2c2219;
        text-align: right;
    }}
    .ingredients, .directions {{
        font-size: 11.5px;
        line-height: 1.45;
        color: #4b3c2f;
        white-space: pre-wrap;
        word-break: break-word;
    }}
    .ingredients {{ margin-bottom: 6px; }}
</style>
</head>
<body>
    <div class="page">
        <div class="hero">
            <div>
                <h1>{escape(title)}</h1>
                <div class="subtitle">A printable weekly meal sheet with meals, ingredients, and directions.</div>
            </div>
            <div class="badge">8.5 × 11</div>
        </div>
        <div class="grid">{''.join(cards_html)}</div>
    </div>
</body>
</html>'''


def build_meal_payload(
    name: str,
    category: str,
    preference: str,
    time_val: str,
    cost: str,
    fill: str,
    ingredient_rows: List[dict],
    directions: str,
    extra_cols: List[str],
    extra_values: Dict[str, str],
) -> dict:
    meal = {
        "description": name.strip(),
        "category": category,
        "preference": preference.strip(),
        "time": time_val.strip(),
        "cost": cost.strip(),
        "fill": fill.strip(),
        "ingredients": ingredient_entries(ingredient_rows),
        "directions": directions.strip(),
    }
    for extra in extra_cols:
        meal[extra] = extra_values.get(extra, "").strip()
    return meal


def normalize_ingredient_name(raw_text: str) -> str:
    entry = normalize_ingredient_entry(raw_text)
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", (entry.get("name") or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def build_meal_prep_tasks(meals: List[dict]) -> List[dict]:
    tasks: List[dict] = []
    for meal in meals:
        meal_name = meal.get("description", "").strip() or "Meal"
        steps = parse_direction_steps(meal.get("directions", ""))
        step_photo_map = meal.get("step_photos", {}) if isinstance(meal.get("step_photos", {}), dict) else {}
        if not steps:
            tasks.append({
                "meal_name": meal_name,
                "step_number": 1,
                "text": "No directions added yet.",
                "photos": [],
            })
            continue
        for step_idx, step_text in enumerate(steps):
            tasks.append({
                "meal_name": meal_name,
                "step_number": step_idx + 1,
                "text": step_text,
                "photos": meal_media_paths(list(step_photo_map.get(str(step_idx), []))),
            })
    return tasks


def meal_prep_summary_rows(meals: List[dict]) -> List[dict]:
    usage: Dict[str, dict] = {}
    for meal in meals:
        meal_name = meal.get("description", "").strip() or "Meal"
        for ingredient in ingredient_display_list(meal.get("ingredients", [])):
            key = normalize_ingredient_name(ingredient) or ingredient.lower().strip()
            if not key:
                continue
            entry = usage.setdefault(key, {"ingredient": ingredient, "meals": set(), "count": 0})
            entry["meals"].add(meal_name)
            entry["count"] += 1
    rows = []
    for entry in sorted(usage.values(), key=lambda item: item["ingredient"].lower()):
        rows.append({
            "Ingredient": entry["ingredient"],
            "Meals Using It": len(entry["meals"]),
            "Used In": ", ".join(sorted(entry["meals"])),
        })
    return rows


def open_meal_prep_mode() -> None:
    st.session_state['meal_prep_mode_active'] = True


def close_meal_prep_mode() -> None:
    st.session_state['meal_prep_mode_active'] = False


def render_meal_prep_mode() -> None:
    meals = selected_unique_meals()
    if not meals:
        st.info("Pick some meals in the planner to use meal prep mode.")
        st.button("Return to planner", on_click=close_meal_prep_mode, use_container_width=True, key="meal_prep_close_empty")
        return

    st.markdown("<div class='deck-kicker'>Meal prep mode</div><div class='deck-title'>Prep everything for this plan</div>", unsafe_allow_html=True)
    top_cols = st.columns([1.1, 1.1, 2.4])
    with top_cols[0]:
        st.button("Return to planner", on_click=close_meal_prep_mode, use_container_width=True, key="meal_prep_close_top")
    with top_cols[1]:
        st.toggle("Mobile friendly mode", key="mobile_mode_planner")
    with top_cols[2]:
        st.caption("Use this view as a single place to prep ingredients, follow every step, and see which meals share ingredients.")

    meal_names = [meal.get("description", "").strip() for meal in meals if meal.get("description", "").strip()]
    st.markdown("<div class='deck-section-title'>Meals in this prep session</div>", unsafe_allow_html=True)
    st.markdown("<div class='meal-prep-chip-row'>" + "".join(f"<span class='meal-prep-chip'>{escape(name)}</span>" for name in meal_names) + "</div>", unsafe_allow_html=True)

    summary_rows = meal_prep_summary_rows(meals)
    st.markdown("<div class='deck-section-title'>Shared ingredients</div>", unsafe_allow_html=True)
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No ingredients found in the selected meals yet.")

    tasks = build_meal_prep_tasks(meals)
    st.markdown("<div class='deck-section-title'>Prep flow</div>", unsafe_allow_html=True)
    for task_idx, task in enumerate(tasks):
        st.markdown("<div class='deck-shell meal-prep-task-shell'>", unsafe_allow_html=True)
        task_cols = st.columns([1.3, 2.2])
        with task_cols[0]:
            st.markdown(f"<div class='meal-prep-step-label'>{escape(task['meal_name'])} · Step {task['step_number']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='deck-column deck-column-directions meal-prep-step-text'>{escape(task['text'])}</div>", unsafe_allow_html=True)
        with task_cols[1]:
            if task['photos']:
                display_paths = task['photos'][:4]
                photo_cols = st.columns(min(2, len(display_paths)))
                for photo_idx, photo_path in enumerate(display_paths):
                    with photo_cols[photo_idx % len(photo_cols)]:
                        st.image(photo_path, use_container_width=True)
            else:
                st.markdown("<div class='deck-photo-empty'>No step photo yet.</div>", unsafe_allow_html=True)
        st.checkbox(f"Mark complete: {task['meal_name']} step {task['step_number']}", key=f"meal_prep_done_{task_idx}")
        st.markdown("</div>", unsafe_allow_html=True)


def render_meal_form(mode: str, meal: dict | None = None) -> dict:
    meal = meal or {}
    extra_cols = custom_columns()
    prefix = "edit_meal" if mode == "edit" else "new_meal"

    name = st.text_input("Meal Name", value=meal.get("description", ""), key=f"{prefix}_description")

    st.markdown("### Ingredients")
    existing_ingredients = ingredient_entries(meal.get("ingredients", []))
    ingredient_count_default = max(len(existing_ingredients), 1)
    ingredient_count = int(
        st.number_input(
            "Number of ingredients",
            min_value=1,
            max_value=50,
            value=int(st.session_state.get(f"{prefix}_ingredient_count", ingredient_count_default)),
            step=1,
            key=f"{prefix}_ingredient_count",
        )
    )

    ingredient_rows: List[dict] = []
    for idx in range(ingredient_count):
        existing = existing_ingredients[idx] if idx < len(existing_ingredients) else {"qty": None, "unit": "", "name": ""}
        row_cols = st.columns([1, 1, 3])
        with row_cols[0]:
            qty_text = st.text_input(
                "Qty",
                value=st.session_state.get(
                    f"{prefix}_qty_{idx}",
                    format_scaled_quantity(existing["qty"]) if existing.get("qty") not in (None, "") else "",
                ),
                key=f"{prefix}_qty_{idx}",
            )
        with row_cols[1]:
            unit_default = ingredient_unit_value(existing)
            unit_options = STANDARD_UNITS + ([unit_default] if unit_default and unit_default not in STANDARD_UNITS else [])
            unit = st.selectbox(
                "Unit",
                unit_options,
                index=unit_options.index(unit_default) if unit_default in unit_options else 0,
                key=f"{prefix}_unit_{idx}",
            )
        with row_cols[2]:
            name_val = st.text_input(
                "Ingredient",
                value=st.session_state.get(f"{prefix}_name_{idx}", ingredient_name_value(existing)),
                key=f"{prefix}_name_{idx}",
            )
        qty_val = _parse_number_token(qty_text)
        if name_val.strip():
            ingredient_rows.append({"qty": qty_val, "unit": normalize_unit(unit), "name": name_val.strip()})

    directions = st.text_area(
        "Directions",
        value=meal.get("directions", ""),
        key=f"{prefix}_directions",
        height=140,
        placeholder="Cooking directions, prep notes, or serving instructions.",
    )

    category_default = meal.get("category", CATEGORY_OPTIONS[0]) or CATEGORY_OPTIONS[0]
    category = st.selectbox(
        "Category",
        CATEGORY_OPTIONS,
        index=CATEGORY_OPTIONS.index(category_default) if category_default in CATEGORY_OPTIONS else 0,
        key=f"{prefix}_category",
    )

    col1, col2, col3, col4 = st.columns(4)
    pref_default = meal.get("preference", "") or ""
    time_default = meal.get("time", "") or ""
    cost_default = meal.get("cost", "") or ""
    fill_default = meal.get("fill", "") or ""

    with col1:
        preference = st.selectbox("Preference", PREFERENCE_OPTIONS, index=PREFERENCE_OPTIONS.index(pref_default) if pref_default in PREFERENCE_OPTIONS else 0, key=f"{prefix}_preference")
    with col2:
        time_val = st.selectbox("Time", TIME_OPTIONS, index=TIME_OPTIONS.index(time_default) if time_default in TIME_OPTIONS else 0, key=f"{prefix}_time")
    with col3:
        cost = st.selectbox("Cost", COST_OPTIONS, index=COST_OPTIONS.index(cost_default) if cost_default in COST_OPTIONS else 0, key=f"{prefix}_cost")
    with col4:
        fill = st.selectbox("Fill", FILL_OPTIONS, index=FILL_OPTIONS.index(fill_default) if fill_default in FILL_OPTIONS else 0, key=f"{prefix}_fill")

    extra_values: Dict[str, str] = {}
    if extra_cols:
        extra_ui_cols = st.columns(2)
        for idx, extra in enumerate(extra_cols):
            with extra_ui_cols[idx % 2]:
                extra_values[extra] = st.text_input(extra.replace("_", " ").title(), value=str(meal.get(extra, "")), key=f"{prefix}_{extra}")

    meal_payload = build_meal_payload(
        name=name,
        category=category,
        preference=preference,
        time_val=time_val,
        cost=cost,
        fill=fill,
        ingredient_rows=ingredient_rows,
        directions=directions,
        extra_cols=extra_cols,
        extra_values=extra_values,
    )

    st.markdown("### Photos")
    meal_photo_files = st.file_uploader("Meal Photos", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"{prefix}_meal_photos_upload", help="Upload finished-dish photos.")

    existing_meal_photos = meal_media_paths(list(meal.get("meal_photos", [])))
    if existing_meal_photos:
        st.caption("Existing meal photos")
        st.image(existing_meal_photos, use_container_width=True)

    ingredient_photo_files: Dict[str, list] = {}
    ingredients = meal_payload.get("ingredients", [])
    if ingredients:
        st.markdown("#### Ingredient Photos")
        for ingredient in ingredients:
            photo_key = ingredient_photo_key(ingredient)
            with st.expander(format_ingredient(ingredient), expanded=False):
                ingredient_photo_files[photo_key] = st.file_uploader(
                    f"{photo_key} Photos",
                    type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=True,
                    key=f"{prefix}_ingredient_photo_{slugify_for_path(photo_key)}",
                )
                existing_paths = meal_media_paths(list((meal.get("ingredient_photos", {}) or {}).get(photo_key, [])))
                if existing_paths:
                    st.image(existing_paths, width=140)
    else:
        st.caption("Add ingredients above to enable ingredient photo uploads.")

    step_photo_files: Dict[str, list] = {}
    steps = parse_direction_steps(meal_payload.get("directions", ""))
    if steps:
        st.markdown("#### Step Photos")
        for step_index, step_text in enumerate(steps):
            label = f"Step {step_index + 1}"
            with st.expander(label, expanded=False):
                st.write(step_text)
                step_photo_files[str(step_index)] = st.file_uploader(f"{label} Photos", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key=f"{prefix}_step_photo_{step_index}")
                existing_paths = meal_media_paths(list((meal.get("step_photos", {}) or {}).get(str(step_index), [])))
                if existing_paths:
                    st.image(existing_paths, use_container_width=True)
    else:
        st.caption("Add directions above to enable step photo uploads.")

    return {
        "meal": meal_payload,
        "meal_photo_files": meal_photo_files or [],
        "ingredient_photo_files": ingredient_photo_files,
        "step_photo_files": step_photo_files,
    }



def parse_direction_steps(directions: str) -> List[str]:
    text = (directions or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return []

    numbered_parts = re.split(r'(?:^|\n)\s*(?:step\s*)?\d+[\).:-]\s*', text, flags=re.IGNORECASE)
    numbered_steps = [part.strip(' -•\t\n') for part in numbered_parts if part.strip(' -•\t\n')]
    if len(numbered_steps) >= 2:
        return numbered_steps

    paragraph_steps = [part.strip() for part in re.split(r'\n\s*\n+', text) if part.strip()]
    if len(paragraph_steps) >= 2:
        return paragraph_steps

    bullet_steps = [part.strip(' -•\t') for part in text.split('\n') if part.strip(' -•\t')]
    if len(bullet_steps) >= 2:
        return bullet_steps

    return [text]

def ingredient_matches_step(ingredient, step_text: str) -> bool:
    ingredient_text = ingredient_name_text(ingredient).lower().strip()
    step_lower = (step_text or '').lower()
    if not ingredient_text or not step_lower:
        return False
    if ingredient_text in step_lower:
        return True
    tokens = [token for token in re.findall(r'[a-zA-Z]+', ingredient_text) if len(token) >= 3]
    return any(token in step_lower for token in tokens)



def render_ingredient_slide_markup(ingredients: List[str], ingredient_photo_map: dict, step_text: str) -> str:
    if not ingredients:
        return "<div class='deck-ingredient deck-ingredient-empty'>No ingredients listed.</div>"

    cards = []
    for ingredient in ingredients:
        matched = ingredient_matches_step(ingredient, step_text)
        ingredient_paths = meal_media_paths(list((ingredient_photo_map or {}).get(ingredient, [])))
        title_class = "deck-ingredient-name deck-ingredient-name-active" if matched else "deck-ingredient-name"
        card_class = "deck-ingredient deck-ingredient-active" if matched else "deck-ingredient"
        photo_html = ""
        if ingredient_paths:
            photo_html = f"<div class='deck-ingredient-thumb-wrap'><img class='deck-ingredient-thumb' src='file://{escape(ingredient_paths[0])}' alt='{escape(ingredient)}'></div>"
        cards.append(
            f"<div class='{card_class}'>"
            f"{photo_html}"
            f"<div class='deck-ingredient-body'><div class='{title_class}'>{escape(ingredient)}</div></div>"
            f"</div>"
        )
    return "".join(cards)

def directions_has_cover_slide(meal: dict) -> bool:
    return bool(meal_media_paths(list(meal.get('meal_photos', []))))

def directions_total_slides(meal: dict) -> int:
    steps = parse_direction_steps(meal.get('directions', ''))
    if not steps:
        return 1 if directions_has_cover_slide(meal) else 0
    return len(steps) + (1 if directions_has_cover_slide(meal) else 0)

def open_directions_deck(meal_name: str) -> None:
    st.session_state['directions_view_active'] = True
    st.session_state['directions_meal_name'] = meal_name
    st.session_state['directions_step_index'] = 0

def close_directions_deck() -> None:
    st.session_state['directions_view_active'] = False
    st.session_state['directions_meal_name'] = ''
    st.session_state['directions_step_index'] = 0

def change_direction_step(delta: int) -> None:
    meal_name = st.session_state.get('directions_meal_name', '')
    meal = meal_lookup().get(meal_name, {})
    total = directions_total_slides(meal)
    if total <= 0:
        st.session_state['directions_step_index'] = 0
        return
    current = int(st.session_state.get('directions_step_index', 0))
    st.session_state['directions_step_index'] = max(0, min(total - 1, current + delta))


def get_meals_slide_snapshot() -> List[dict]:
    snapshot_names = st.session_state.get('meals_slide_names_snapshot', [])
    if snapshot_names:
        lookup = meal_lookup()
        return [lookup[name] for name in snapshot_names if name in lookup]
    return selected_unique_meals()


def selected_unique_meals() -> List[dict]:
    unique_meals: List[dict] = []
    seen_names = set()
    for meal in selected_meals():
        meal_name = meal.get("description", "").strip()
        if not meal_name or meal_name in seen_names:
            continue
        seen_names.add(meal_name)
        unique_meals.append(meal)
    return unique_meals


def open_meals_slide_deck() -> None:
    st.session_state['meals_slide_deck_active'] = True
    st.session_state['meals_slide_index'] = 0
    st.session_state['meals_slide_names_snapshot'] = [
        meal.get("description", "").strip()
        for meal in selected_unique_meals()
        if meal.get("description", "").strip()
    ]


def close_meals_slide_deck() -> None:
    st.session_state['meals_slide_deck_active'] = False
    st.session_state['meals_slide_index'] = 0
    st.session_state['meals_slide_names_snapshot'] = []


def change_meals_slide(delta: int) -> None:
    meals = get_meals_slide_snapshot()
    total = len(meals)
    if total <= 0:
        st.session_state['meals_slide_index'] = 0
        return
    current = int(st.session_state.get('meals_slide_index', 0))
    st.session_state['meals_slide_index'] = max(0, min(total - 1, current + delta))


def render_meals_slide_deck() -> None:
    meals = selected_unique_meals()
    if not meals:
        st.info("Pick some meals in the planner to use the meals slide deck.")
        st.button("Return to home", on_click=close_meals_slide_deck, use_container_width=True)
        return

    slide_index = int(st.session_state.get("meals_slide_index", 0))
    slide_index = max(0, min(len(meals) - 1, slide_index))
    st.session_state["meals_slide_index"] = slide_index

    meal = meals[slide_index]
    meal_name = meal.get("description", "").strip() or "Meal"
    ingredients = ingredient_display_list(meal.get("ingredients", []))
    directions = (meal.get("directions", "") or "").strip()
    steps = parse_direction_steps(directions)
    meal_photo_paths = meal_media_paths(list(meal.get("meal_photos", [])))
    step_photo_paths: List[str] = []
    step_photo_map = meal.get("step_photos", {}) if isinstance(meal.get("step_photos", {}), dict) else {}
    for step_idx in range(len(steps)):
        step_photo_paths.extend(meal_media_paths(list(step_photo_map.get(str(step_idx), []))))

    top_nav1, top_nav2, top_nav3, top_nav4, top_nav5 = st.columns([1, 1, 1.2, 1.4, 2.2])
    with top_nav1:
        st.button(
            "Back",
            on_click=change_meals_slide,
            args=(-1,),
            disabled=(slide_index == 0),
            use_container_width=True,
            key='meals_deck_back'
        )
    with top_nav2:
        st.button(
            "Next",
            on_click=change_meals_slide,
            args=(1,),
            disabled=(slide_index >= len(meals) - 1),
            use_container_width=True,
            key='meals_deck_next'
        )
    with top_nav3:
        st.button("Return to home", on_click=close_meals_slide_deck, use_container_width=True, key='meals_deck_close')
    with top_nav4:
        st.toggle('Mobile friendly mode', key='mobile_mode_meals_deck')
    with top_nav5:
        st.markdown(
            f"<div class='deck-step-chip deck-step-chip-top'>Slide {slide_index + 1} of {len(meals)}</div>",
            unsafe_allow_html=True,
        )

    mobile_mode = bool(st.session_state.get('mobile_mode_meals_deck', False))
    st.markdown(
        f"<div class='deck-kicker'>Meals slide deck</div><div class='deck-title'>{escape(meal_name)}</div>",
        unsafe_allow_html=True,
    )

    if mobile_mode:
        st.markdown("<div class='deck-section-title'>Finished meal photo</div>", unsafe_allow_html=True)
        if meal_photo_paths:
            st.image(meal_photo_paths[0], use_container_width=True)
        else:
            st.markdown("<div class='deck-photo-empty'>No finished meal photo yet.</div>", unsafe_allow_html=True)

        st.markdown("<div class='deck-section-title'>Ingredients</div>", unsafe_allow_html=True)
        if ingredients:
            ingredient_markup = "<ul class='ingredient-list'>" + "".join(
                f"<li>{escape(item)}</li>" for item in ingredients
            ) + "</ul>"
            st.markdown(f"<div class='deck-column'>{ingredient_markup}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='deck-photo-empty'>No ingredients listed.</div>", unsafe_allow_html=True)

        st.markdown("<div class='deck-section-title'>Steps</div>", unsafe_allow_html=True)
        if directions:
            if steps:
                directions_markup = "".join(
                    f"<div style='margin-bottom:0.45rem;'><strong>Step {idx + 1}:</strong> {escape(step)}</div>"
                    for idx, step in enumerate(steps)
                )
            else:
                directions_markup = escape(directions)
            st.markdown(f"<div class='deck-column deck-column-directions'>{directions_markup}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='deck-photo-empty'>No directions added yet.</div>", unsafe_allow_html=True)
    else:
        top_left, top_right = st.columns([1.05, 1.15])
        with top_left:
            st.markdown("<div class='deck-section-title'>Ingredients</div>", unsafe_allow_html=True)
            if ingredients:
                ingredient_markup = "<ul class='ingredient-list'>" + "".join(
                    f"<li>{escape(item)}</li>" for item in ingredients
                ) + "</ul>"
                st.markdown(
                    f"<div class='deck-column'>{ingredient_markup}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("<div class='deck-photo-empty'>No ingredients listed.</div>", unsafe_allow_html=True)

        with top_right:
            st.markdown("<div class='deck-section-title'>Finished meal photo</div>", unsafe_allow_html=True)
            if meal_photo_paths:
                st.image(meal_photo_paths[0], use_container_width=True)
            else:
                st.markdown("<div class='deck-photo-empty'>No finished meal photo yet.</div>", unsafe_allow_html=True)

        st.markdown("<div class='deck-section-title'>Directions</div>", unsafe_allow_html=True)
        if directions:
            if steps:
                directions_markup = "".join(
                    f"<div style='margin-bottom:0.45rem;'><strong>Step {idx + 1}:</strong> {escape(step)}</div>"
                    for idx, step in enumerate(steps)
                )
            else:
                directions_markup = escape(directions)
            st.markdown(
                f"<div class='deck-column deck-column-directions'>{directions_markup}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div class='deck-photo-empty'>No directions added yet.</div>", unsafe_allow_html=True)

        st.markdown("<div class='deck-section-title'>Step photos</div>", unsafe_allow_html=True)
        if step_photo_paths:
            display_paths = step_photo_paths[:8]
            step_cols = st.columns(min(4, len(display_paths)))
            for idx, photo_path in enumerate(display_paths):
                with step_cols[idx % len(step_cols)]:
                    st.image(photo_path, use_container_width=True)
        else:
            st.markdown("<div class='deck-photo-empty'>No step photos yet.</div>", unsafe_allow_html=True)


def render_directions_deck(meal_name: str) -> None:
    meal = meal_lookup().get(meal_name, {})
    if not meal:
        st.warning("That meal could not be found.")
        st.button("Return to home", key="directions_slide_close", on_click=close_directions_deck, use_container_width=True)
        return

    steps = parse_direction_steps(meal.get("directions", ""))
    ingredients = ingredient_display_list(meal.get("ingredients", []))
    meal_photo_paths = meal_media_paths(list(meal.get("meal_photos", [])))
    has_cover = bool(meal_photo_paths)
    total_slides = len(steps) + (1 if has_cover else 0)

    if total_slides <= 0:
        st.warning("This meal does not have any directions or meal photos yet.")
        st.button("Return to home", key="directions_slide_close", on_click=close_directions_deck, use_container_width=True)
        return

    slide_index = int(st.session_state.get("directions_step_index", 0))
    slide_index = max(0, min(total_slides - 1, slide_index))
    st.session_state["directions_step_index"] = slide_index

    top_nav1, top_nav2, top_nav3, top_nav4 = st.columns([1, 1, 1.15, 3.2])
    with top_nav1:
        st.button("Back", key="directions_slide_back", on_click=change_direction_step, args=(-1,), disabled=(slide_index == 0), use_container_width=True)
    with top_nav2:
        st.button("Next", key="directions_slide_next", on_click=change_direction_step, args=(1,), disabled=(slide_index >= total_slides - 1), use_container_width=True)
    with top_nav3:
        st.button("Return to home", key="directions_slide_close", on_click=close_directions_deck, use_container_width=True)
    with top_nav4:
        st.markdown(
            f"<div class='deck-step-chip deck-step-chip-top'>Slide {slide_index + 1} of {total_slides}</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<div class='deck-kicker'>Directions deck</div><div class='deck-title'>{escape(meal_name)}</div>",
        unsafe_allow_html=True,
    )

    if has_cover and slide_index == 0:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(meal_photo_paths[0], width=500)
        return

    step_index = slide_index - 1 if has_cover else slide_index
    if step_index < 0 or step_index >= len(steps):
        st.warning("This meal does not have any directions yet.")
        st.button("Return to home", key="directions_slide_close", on_click=close_directions_deck, use_container_width=True)
        return

    step_text = steps[step_index]
    step_photo_paths = meal_media_paths(list((meal.get("step_photos", {}) or {}).get(str(step_index), [])))
    ingredient_photo_map = meal.get("ingredient_photos", {}) if isinstance(meal.get("ingredient_photos", {}), dict) else {}

    #st.markdown("<div class='deck-shell'>", unsafe_allow_html=True)
    left_col, right_col = st.columns([0.95, 1.1])

    with right_col:
        st.markdown("<div class='deck-section-title'>Ingredients</div>", unsafe_allow_html=True)
        if not ingredients:
            st.markdown("<div class='deck-ingredient-empty'>No ingredients listed.</div>", unsafe_allow_html=True)
        else:
            tile_cols = st.columns(5, gap="small")
            for idx, ingredient in enumerate(ingredients):
                matched = ingredient_matches_step(ingredient, step_text)
                name_class = "deck-ingredient-name deck-ingredient-name-active" if matched else "deck-ingredient-name"
                ingredient_paths = meal_media_paths(list(ingredient_photo_map.get(ingredient_photo_key(ingredient), [])))
                with tile_cols[idx % 5]:
                    st.markdown("<div class='deck-ingredient-tile'>", unsafe_allow_html=True)
                    if ingredient_paths:
                        st.image(ingredient_paths[0], use_container_width=True)
                    else:
                        st.markdown("<div class='deck-ingredient-photo-empty'></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='{name_class}'>{escape(ingredient)}</div>", unsafe_allow_html=True)
                    #st.markdown("</div>", unsafe_allow_html=True)

    with left_col:
        st.markdown(f"<div class='deck-section-title'>Step {step_index + 1} directions</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='deck-column deck-column-directions deck-column-directions-auto'><div class='deck-step-text'>{escape(step_text)}</div></div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='deck-section-title deck-step-photo-title'>Step {step_index + 1} photo</div>", unsafe_allow_html=True)
        if step_photo_paths:
            st.image(step_photo_paths[0], use_container_width=True)
        else:
            st.markdown("<div class='deck-photo-empty'>No photo for this step yet.</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)



def _parse_number_token(token: str) -> float | None:
    token = (token or '').strip()
    if not token:
        return None
    try:
        return float(token)
    except Exception:
        pass

    if ' ' in token:
        parts = [part for part in token.split() if part]
        if len(parts) == 2 and '/' in parts[1]:
            whole = _parse_number_token(parts[0])
            frac = _parse_number_token(parts[1])
            if whole is not None and frac is not None:
                return whole + frac
    if '/' in token:
        try:
            numerator, denominator = token.split('/', 1)
            return float(numerator) / float(denominator)
        except Exception:
            return None
    return None


def parse_ingredient_amount_text(raw_text: str) -> tuple[float | None, str, str]:
    text = (raw_text or '').strip()
    if not text:
        return None, '', ''

    parts = text.split()
    qty: float | None = None
    unit = ''
    name = text

    if parts:
        remainder = parts[:]
        first = _parse_number_token(remainder[0])
        if first is not None:
            qty = first
            remainder = remainder[1:]
            if remainder and '/' in remainder[0]:
                frac = _parse_number_token(remainder[0])
                if frac is not None:
                    qty = (qty or 0.0) + frac
                    remainder = remainder[1:]
            if remainder:
                candidate = normalize_unit(remainder[0])
                if candidate in STANDARD_UNITS:
                    unit = candidate
                    remainder = remainder[1:]
            name = ' '.join(remainder).strip() or text
    return qty, unit, name

def format_scaled_quantity(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    if value < 10:
        rounded_quarter = round(value * 4) / 4
        if abs(value - rounded_quarter) < 1e-9:
            whole = int(rounded_quarter)
            frac = rounded_quarter - whole
            frac_map = {0.25: '1/4', 0.5: '1/2', 0.75: '3/4'}
            if frac == 0:
                return str(whole)
            frac_text = frac_map.get(round(frac, 2), f'{rounded_quarter:.2f}'.rstrip('0').rstrip('.'))
            return f'{whole} {frac_text}'.strip() if whole else frac_text
    return f'{value:.2f}'.rstrip('0').rstrip('.')



def render_meal_prep_tab() -> None:
    meals = sorted([meal.get('description', '') for meal in load_meals() if meal.get('description')], key=str.lower)
    if not meals:
        st.info('Add at least one meal in the Meal Library to use meal prep.')
        return

    mobile_mode = st.toggle('Mobile friendly mode', key='mobile_mode_prep')

    st.markdown('### Meal prep')
    selected_meal_names = st.multiselect(
        'Choose meals',
        meals,
        default=st.session_state.get('prep_selected_meals', []),
        key='prep_selected_meals',
    )

    if not selected_meal_names:
        st.info('Choose one or more meals to build a combined prep ingredient list.')
        return

    st.caption('Set how many times you want to make each meal, then adjust ingredient amounts and units as needed. The app will combine similar ingredients and scale them together.')

    meal_quantities: dict[str, float] = {}
    st.markdown('### Selected meals')
    if mobile_mode:
        for meal_name in selected_meal_names:
            meal_quantities[meal_name] = float(
                st.number_input(
                    f'{meal_name} count',
                    min_value=0.0,
                    step=1.0,
                    value=float(st.session_state.get(f'prep_qty_{meal_name}', 1.0)),
                    key=f'prep_qty_{meal_name}',
                )
            )
    else:
        qty_cols = st.columns(min(3, len(selected_meal_names)))
        for idx, meal_name in enumerate(selected_meal_names):
            with qty_cols[idx % len(qty_cols)]:
                meal_quantities[meal_name] = float(
                    st.number_input(
                        f'{meal_name} count',
                        min_value=0.0,
                        step=1.0,
                        value=float(st.session_state.get(f'prep_qty_{meal_name}', 1.0)),
                        key=f'prep_qty_{meal_name}',
                    )
                )

    prep_rows: List[dict] = []
    lookup = meal_lookup()
    for meal_name in selected_meal_names:
        meal = lookup.get(meal_name, {})
        meal_count = float(meal_quantities.get(meal_name, 0.0) or 0.0)
        if meal_count <= 0:
            continue

        base_ingredients = ingredient_entries(meal.get('ingredients', []))
        st.markdown(f'### {meal_name} ingredients')
        if not base_ingredients:
            st.info(f'{meal_name} does not have any ingredients yet.')
            continue

        for idx, ingredient in enumerate(base_ingredients):
            guessed_qty = ingredient_qty_value(ingredient, default=0.0)
            guessed_unit = ingredient_unit_value(ingredient)
            guessed_name = ingredient_name_value(ingredient) or format_ingredient(ingredient)
            safe_meal = slugify_for_path(meal_name)
            if mobile_mode:
                item_name = st.text_input(
                    f'Ingredient',
                    value=st.session_state.get(f'prep_name_{safe_meal}_{idx}', guessed_name),
                    key=f'prep_name_{safe_meal}_{idx}',
                )
                qty = st.number_input(
                    f'Qty per meal',
                    min_value=0.0,
                    step=0.25,
                    value=float(st.session_state.get(f'prep_item_qty_{safe_meal}_{idx}', guessed_qty or 0.0)),
                    key=f'prep_item_qty_{safe_meal}_{idx}',
                )
                prep_unit_default = st.session_state.get(f'prep_unit_{safe_meal}_{idx}', guessed_unit)
                prep_unit_options = STANDARD_UNITS + ([prep_unit_default] if prep_unit_default and prep_unit_default not in STANDARD_UNITS else [])
                unit = st.selectbox(
                    f'Unit',
                    prep_unit_options,
                    index=prep_unit_options.index(prep_unit_default) if prep_unit_default in prep_unit_options else 0,
                    key=f'prep_unit_{safe_meal}_{idx}',
                )
            else:
                row_cols = st.columns([2.5, 1.0, 1.2])
                with row_cols[0]:
                    item_name = st.text_input(
                        'Ingredient',
                        value=st.session_state.get(f'prep_name_{safe_meal}_{idx}', guessed_name),
                        key=f'prep_name_{safe_meal}_{idx}',
                    )
                with row_cols[1]:
                    qty = st.number_input(
                        'Qty per meal',
                        min_value=0.0,
                        step=0.25,
                        value=float(st.session_state.get(f'prep_item_qty_{safe_meal}_{idx}', guessed_qty or 0.0)),
                        key=f'prep_item_qty_{safe_meal}_{idx}',
                    )
                with row_cols[2]:
                    prep_unit_default = st.session_state.get(f'prep_unit_{safe_meal}_{idx}', guessed_unit)
                    prep_unit_options = STANDARD_UNITS + ([prep_unit_default] if prep_unit_default and prep_unit_default not in STANDARD_UNITS else [])
                    unit = st.selectbox(
                        'Unit',
                        prep_unit_options,
                        index=prep_unit_options.index(prep_unit_default) if prep_unit_default in prep_unit_options else 0,
                        key=f'prep_unit_{safe_meal}_{idx}',
                    )
            prep_rows.append({
                'meal_name': meal_name,
                'name': item_name.strip(),
                'qty': float(qty),
                'unit': unit.strip(),
                'meal_count': meal_count,
            })

    st.markdown('### Additional ingredients')
    st.caption('Add ingredients here that are not on the selected meal ingredient lists.')
    extra_count = int(
        st.number_input(
            'Number of additional ingredients',
            min_value=0,
            max_value=30,
            step=1,
            value=int(st.session_state.get('prep_extra_count', 0)),
            key='prep_extra_count',
        )
    )

    for extra_idx in range(extra_count):
        if mobile_mode:
            extra_name = st.text_input('Ingredient', key=f'prep_extra_name_{extra_idx}', placeholder='Extra ingredient')
            extra_qty = st.number_input('Qty per prep', min_value=0.0, step=0.25, value=float(st.session_state.get(f'prep_extra_qty_{extra_idx}', 0.0)), key=f'prep_extra_qty_{extra_idx}')
            extra_unit = st.selectbox('Unit', STANDARD_UNITS, key=f'prep_extra_unit_{extra_idx}')
            extra_meals = st.number_input('Multiplier', min_value=0.0, step=1.0, value=float(st.session_state.get(f'prep_extra_mult_{extra_idx}', 1.0)), key=f'prep_extra_mult_{extra_idx}')
        else:
            row_cols = st.columns([2.2, 1, 1.1, 1.4])
            with row_cols[0]:
                extra_name = st.text_input('Ingredient', key=f'prep_extra_name_{extra_idx}', placeholder='Extra ingredient')
            with row_cols[1]:
                extra_qty = st.number_input('Qty per prep', min_value=0.0, step=0.25, value=float(st.session_state.get(f'prep_extra_qty_{extra_idx}', 0.0)), key=f'prep_extra_qty_{extra_idx}')
            with row_cols[2]:
                extra_unit = st.selectbox('Unit', STANDARD_UNITS, key=f'prep_extra_unit_{extra_idx}')
            with row_cols[3]:
                extra_meals = st.number_input('Multiplier', min_value=0.0, step=1.0, value=float(st.session_state.get(f'prep_extra_mult_{extra_idx}', 1.0)), key=f'prep_extra_mult_{extra_idx}')
        if extra_name.strip():
            prep_rows.append({
                'meal_name': 'Additional',
                'name': extra_name.strip(),
                'qty': float(extra_qty),
                'unit': extra_unit.strip(),
                'meal_count': float(extra_meals),
            })

    aggregated: dict[tuple[str, str], dict] = {}
    for row in prep_rows:
        name = row.get('name', '').strip()
        qty = float(row.get('qty', 0.0) or 0.0)
        unit = normalize_unit(row.get('unit', '').strip())
        meal_count = float(row.get('meal_count', 0.0) or 0.0)
        if not name or qty <= 0 or meal_count <= 0:
            continue
        norm_name = normalize_ingredient_name(name) or name.lower().strip()
        key = (norm_name, unit.lower())
        entry = aggregated.setdefault(key, {
            'ingredient': name,
            'unit': unit,
            'total_qty': 0.0,
            'used_in': set(),
        })
        entry['total_qty'] += qty * meal_count
        entry['used_in'].add(str(row.get('meal_name', '')))

    st.markdown('### Combined prep ingredient list')
    if not aggregated:
        st.info('Enter meal counts or ingredient amounts to generate the prep list.')
        return

    output_rows = []
    for (_name_key, _unit_key), entry in sorted(aggregated.items(), key=lambda item: item[1]['ingredient'].lower()):
        output_rows.append({
            'Ingredient': entry['ingredient'],
            'Unit': entry['unit'],
            'Scaled Amount': f"{format_scaled_quantity(entry['total_qty'])} {entry['unit']}".strip(),
            'Used In': ', '.join(sorted(name for name in entry['used_in'] if name)),
        })

    output_df = pd.DataFrame(output_rows)
    st.dataframe(output_df, use_container_width=True, hide_index=True)
    csv_bytes = output_df.to_csv(index=False).encode('utf-8')
    st.download_button('Download meal prep ingredient list (.csv)', csv_bytes, file_name='meal_prep_ingredient_list.csv', mime='text/csv', use_container_width=True)


def render_meal_multiplier_tab() -> None:
    meals = sorted([meal.get('description', '') for meal in load_meals() if meal.get('description')], key=str.lower)
    if not meals:
        st.info('Add at least one meal in the Meal Library to use the meal multiplier.')
        return

    mobile_mode = st.toggle('Mobile friendly mode', key='mobile_mode_multiplier')

    if mobile_mode:
        selected_meal_name = st.selectbox('Choose a meal', meals, key='multiplier_meal_name')
        total_meals = st.number_input('Total number of meals to plan', min_value=1.0, step=1.0, value=float(st.session_state.get('multiplier_total_meals', 1.0)), key='multiplier_total_meals')
    else:
        top_left, top_right = st.columns([1.4, 1])
        with top_left:
            selected_meal_name = st.selectbox('Choose a meal', meals, key='multiplier_meal_name')
        with top_right:
            total_meals = st.number_input('Total number of meals to plan', min_value=1.0, step=1.0, value=float(st.session_state.get('multiplier_total_meals', 1.0)), key='multiplier_total_meals')

    selected_meal = meal_lookup().get(selected_meal_name, {})
    base_ingredients = ingredient_entries(selected_meal.get('ingredients', []))

    st.caption('Enter the amount needed for one meal. The app will multiply it by the total meal count.')

    multiplier_rows: List[dict] = []
    if base_ingredients:
        st.markdown('### Meal ingredients')
        for idx, ingredient in enumerate(base_ingredients):
            guessed_qty = ingredient_qty_value(ingredient, default=0.0)
            guessed_unit = ingredient_unit_value(ingredient)
            guessed_name = ingredient_name_value(ingredient) or format_ingredient(ingredient)
            if mobile_mode:
                item_name = st.text_input('Ingredient', value=guessed_name, key=f'multiplier_name_{idx}')
                qty = st.number_input('Qty per meal', min_value=0.0, step=0.25, value=float(st.session_state.get(f'multiplier_qty_{idx}', guessed_qty or 0.0)), key=f'multiplier_qty_{idx}')
                multiplier_unit_default = st.session_state.get(f'multiplier_unit_{idx}', guessed_unit)
                multiplier_unit_options = STANDARD_UNITS + ([multiplier_unit_default] if multiplier_unit_default and multiplier_unit_default not in STANDARD_UNITS else [])
                unit = st.selectbox('Unit', multiplier_unit_options, index=multiplier_unit_options.index(multiplier_unit_default) if multiplier_unit_default in multiplier_unit_options else 0, key=f'multiplier_unit_{idx}')
            else:
                row_cols = st.columns([2.8, 1.1, 1.3])
                with row_cols[0]:
                    item_name = st.text_input('Ingredient', value=guessed_name, key=f'multiplier_name_{idx}')
                with row_cols[1]:
                    qty = st.number_input('Qty per meal', min_value=0.0, step=0.25, value=float(st.session_state.get(f'multiplier_qty_{idx}', guessed_qty or 0.0)), key=f'multiplier_qty_{idx}')
                with row_cols[2]:
                    multiplier_unit_default = st.session_state.get(f'multiplier_unit_{idx}', guessed_unit)
                    multiplier_unit_options = STANDARD_UNITS + ([multiplier_unit_default] if multiplier_unit_default and multiplier_unit_default not in STANDARD_UNITS else [])
                    unit = st.selectbox('Unit', multiplier_unit_options, index=multiplier_unit_options.index(multiplier_unit_default) if multiplier_unit_default in multiplier_unit_options else 0, key=f'multiplier_unit_{idx}')
            multiplier_rows.append({'name': item_name.strip(), 'qty': float(qty), 'unit': unit.strip()})
    else:
        st.info('This meal does not have any ingredients yet.')

    st.markdown('### Additional ingredients')
    st.caption("Add ingredients here that are not on the meal's main ingredient list.")
    extra_count = int(st.number_input('Number of additional ingredients', min_value=0, max_value=20, step=1, value=int(st.session_state.get('multiplier_extra_count', 0)), key='multiplier_extra_count'))

    for extra_idx in range(extra_count):
        if mobile_mode:
            extra_name = st.text_input('Ingredient', key=f'multiplier_extra_name_{extra_idx}', placeholder='Extra ingredient')
            extra_qty = st.number_input('Qty per meal', min_value=0.0, step=0.25, value=float(st.session_state.get(f'multiplier_extra_qty_{extra_idx}', 0.0)), key=f'multiplier_extra_qty_{extra_idx}')
            extra_unit = st.selectbox('Unit', STANDARD_UNITS, key=f'multiplier_extra_unit_{extra_idx}')
            extra_total = extra_qty * float(total_meals)
            display_value = f"{format_scaled_quantity(extra_total)} {extra_unit}".strip()
            st.text_input('Scaled total', value=display_value, disabled=True, key=f'multiplier_extra_total_{extra_idx}')
        else:
            row_cols = st.columns([2.2, 1, 1.1, 1.4])
            with row_cols[0]:
                extra_name = st.text_input('Ingredient', key=f'multiplier_extra_name_{extra_idx}', placeholder='Extra ingredient')
            with row_cols[1]:
                extra_qty = st.number_input('Qty per meal', min_value=0.0, step=0.25, value=float(st.session_state.get(f'multiplier_extra_qty_{extra_idx}', 0.0)), key=f'multiplier_extra_qty_{extra_idx}')
            with row_cols[2]:
                extra_unit = st.selectbox('Unit', STANDARD_UNITS, key=f'multiplier_extra_unit_{extra_idx}')
            with row_cols[3]:
                extra_total = extra_qty * float(total_meals)
                display_value = f"{format_scaled_quantity(extra_total)} {extra_unit}".strip()
                st.text_input('Scaled total', value=display_value, disabled=True, key=f'multiplier_extra_total_{extra_idx}')
        if extra_name.strip():
            multiplier_rows.append({'name': extra_name.strip(), 'qty': float(extra_qty), 'unit': extra_unit.strip()})

    aggregated: dict[tuple[str, str], float] = {}
    for row in multiplier_rows:
        name = row.get('name', '').strip()
        qty = float(row.get('qty', 0.0) or 0.0)
        unit = normalize_unit(row.get('unit', '').strip())
        if not name or qty <= 0:
            continue
        key = (normalize_ingredient_name(name), unit.lower())
        aggregated[key] = aggregated.get(key, 0.0) + (qty * float(total_meals))

    st.markdown('### Scaled ingredient list')
    if not aggregated:
        st.info('Enter at least one ingredient amount to generate the scaled list.')
        return

    output_rows = []
    for (name_key, unit_key), total_qty in sorted(aggregated.items(), key=lambda item: item[0][0]):
        display_name = next((row['name'] for row in multiplier_rows if row.get('name', '').strip().lower() == name_key), name_key.title())
        display_unit = next((row['unit'] for row in multiplier_rows if row.get('name', '').strip().lower() == name_key and row.get('unit', '').strip().lower() == unit_key), unit_key)
        output_rows.append({
            'Ingredient': display_name,
            'Unit': display_unit,
            'Scaled Amount': f"{format_scaled_quantity(total_qty)} {display_unit}".strip(),
        })

    st.dataframe(pd.DataFrame(output_rows), use_container_width=True, hide_index=True)
    csv_bytes = pd.DataFrame(output_rows).to_csv(index=False).encode('utf-8')
    st.download_button('Download scaled ingredient list (.csv)', csv_bytes, file_name='scaled_ingredient_list.csv', mime='text/csv', use_container_width=True)


def section_divider(thickness: int = 1, margin: str = "0.75rem 0") -> None:
    st.markdown(
        f"<hr style='border: 0; border-top: {thickness}px solid rgba(148, 163, 184, 0.35); margin: {margin};'>",
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="JDs Crazy Meal Planner", page_icon="🍽️", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px;}
      div[data-testid="stSelectbox"] label {font-weight: 600;}
      .day-header { text-align: center; font-size: 1rem; font-weight: 700; margin-bottom: 0.1rem; }
      .date-header { text-align: center; color: #777; font-size: 0.82rem; margin-bottom: 0.7rem; }
      .ingredient-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.85rem; }
      .ingredient-card { border: 1px solid rgba(128,128,128,0.32); border-radius: 16px; padding: 0.8rem 0.95rem; min-height: 190px; background: transparent; box-shadow: none; }
      .ingredient-title { font-weight: 700; margin-bottom: 0.45rem; }
      .ingredient-list { margin: 0; padding-left: 1rem; line-height: 1.35; font-size: 0.94rem; }
      .ingredient-empty { color: #777; font-style: italic; }
      .row-label { font-weight: 700; padding-top: 0.55rem; white-space: nowrap; }
      .meal-grid-spacer { height: 1.9rem; }
      .deck-shell { border: 1px solid rgba(148, 163, 184, 0.22); border-radius: 20px; padding: 0.85rem; background: rgba(255,255,255,0.02); }
      .deck-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 0.75rem; }
      .deck-kicker { text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.72rem; color: #94a3b8; font-weight: 700; }
      .deck-title { font-size: 1.45rem; font-weight: 800; line-height: 1.08; margin-bottom: 0.15rem; }
      .deck-step-chip { border: 1px solid rgba(148,163,184,0.3); border-radius: 999px; padding: 0.32rem 0.7rem; font-weight: 700; white-space: nowrap; font-size: 0.88rem; text-align: center; }
      .deck-step-chip-top { margin-top: 0.12rem; display: inline-block; width: 100%; }
      .deck-card { display: grid; grid-template-columns: minmax(240px, 0.92fr) minmax(300px, 1.2fr); gap: 0.8rem; }
      .deck-column { border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 16px; padding: 0.8rem; background: rgba(255,255,255,0.015); }
      .deck-column-directions { padding: 0.58rem 0.72rem; margin-bottom: 0.45rem; }\n      .deck-column-directions-auto { min-height: 0; }\n      .deck-step-photo-title { margin-top: 0.2rem; }
      .deck-section-title { font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; color: #94a3b8; margin-bottom: 0.4rem; }
      .deck-ingredient-list-wrap { display: grid; gap: 0.08rem; }
      .deck-ingredient { border: none; border-radius: 0; padding: 0.08rem 0; display: grid; grid-template-columns: 32px minmax(0,1fr); gap: 0.18rem; align-items: center; min-height: 34px; background: transparent; box-shadow: none; }
      .deck-ingredient-active { border: none; background: transparent; box-shadow: none; }
      .deck-ingredient-empty { color: #777; font-style: italic; display:block; padding: 0.35rem 0; }
      .deck-ingredient-thumb-wrap { width: 100%; height: auto; border-radius: 10px; overflow: hidden; background: rgba(255,255,255,0.03); }
      .deck-ingredient-thumb { width: 100%; aspect-ratio: 1 / 1; object-fit: cover; display:block; }
      .deck-ingredient-body { min-width: 0; display:block; min-height: 0; }
      .deck-ingredient-name { font-size: 0.8rem; line-height: 1.08; word-break: break-word; margin: 0; padding: 0.22rem 0 0; display:block; width:100%; text-align:center; }
      .deck-ingredient-name-active { font-weight: 800; font-size: 0.9rem; color: #b91c1c; font-style: normal; }
      .deck-step-text { font-size: 0.96rem; line-height: 1.34; white-space: pre-wrap; word-break: break-word; }
      .deck-note { margin-top: 0.75rem; font-size: 0.88rem; color: #94a3b8; }
      .deck-ingredient-tile { border: 1px solid rgba(148,163,184,0.16); border-radius: 12px; padding: 0.3rem; margin-bottom: 0.45rem; }
      .deck-ingredient-photo-empty { width: 100%; aspect-ratio: 1 / 1; border: 1px dashed rgba(148,163,184,0.22); border-radius: 10px; background: rgba(255,255,255,0.02); }
      .deck-photo-empty { border: 1px dashed rgba(148,163,184,0.32); border-radius: 12px; min-height: 108px; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-style: italic; padding: 0.6rem; text-align:center; }
      .meal-prep-chip-row { display:flex; flex-wrap:wrap; gap:0.45rem; margin-bottom:0.8rem; }
      .meal-prep-chip { display:inline-block; padding:0.38rem 0.78rem; border-radius:999px; background:rgba(148,163,184,0.16); border:1px solid rgba(148,163,184,0.22); font-weight:700; }
      .meal-prep-task-shell { margin-bottom:0.85rem; }
      .meal-prep-step-label { font-size:0.82rem; text-transform:uppercase; letter-spacing:0.06em; color:#94a3b8; font-weight:700; margin-bottom:0.45rem; }
      .meal-prep-step-text { min-height: 90px; }
      .mobile-day-card { border: 1px solid rgba(148,163,184,0.18); border-radius: 16px; padding: 0.75rem; margin-bottom: 0.8rem; background: rgba(255,255,255,0.02); }
      .mobile-day-title { font-size: 1.05rem; font-weight: 800; margin-bottom: 0.15rem; }
      .mobile-day-date { color: #94a3b8; font-size: 0.85rem; margin-bottom: 0.65rem; }
      .mobile-control-stack .stButton > button, .mobile-control-stack div[data-testid="stDownloadButton"] > button { min-height: 3rem; font-size: 1rem; }
      .mobile-mode-note { color:#94a3b8; margin-bottom:0.5rem; }
      @media (max-width: 900px) {
        .block-container { padding-top: 0.8rem; }
        .ingredient-tiles { grid-template-columns: 1fr; }
        .deck-title { font-size: 1.2rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

apply_saved_schedule_to_session()
settings = load_settings()
st.session_state.setdefault("include_standard_weekly", settings.get("include_standard_weekly", False))
st.session_state.setdefault("standard_weekly_items", settings.get("standard_weekly_items", ""))
st.session_state.setdefault("show_add_meal", False)
st.session_state.setdefault("show_edit_meal", False)
st.session_state.setdefault("directions_view_active", False)
st.session_state.setdefault("directions_meal_name", "")
st.session_state.setdefault("directions_step_index", 0)
st.session_state.setdefault("meals_slide_deck_active", False)
st.session_state.setdefault("meals_slide_index", 0)
st.session_state.setdefault("meals_slide_names_snapshot", [])
st.session_state.setdefault("meal_filter_preference", [])
st.session_state.setdefault("meal_filter_time", [])
st.session_state.setdefault("meal_filter_cost", [])
st.session_state.setdefault("meal_filter_fill", [])
st.session_state.setdefault("num_days", 7)
st.session_state.setdefault("safe_close_requested", False)
st.session_state.setdefault("mobile_friendly_mode", False)
st.session_state.setdefault("mobile_mode_planner", False)
st.session_state.setdefault("mobile_mode_library", False)
st.session_state.setdefault("mobile_mode_multiplier", False)
st.session_state.setdefault("mobile_mode_prep", False)
st.session_state.setdefault("mobile_mode_directions_deck", False)
st.session_state.setdefault("mobile_mode_meals_deck", False)
st.session_state.setdefault("meal_prep_mode_active", False)

st.title("The Ultimate Meal Planner")

selector_tab, library_tab, multiplier_tab, prep_tab = st.tabs(["Meal Planner", "Meal Library", "Meal Multiplier", "Meal Prep"])


def render_planner_grid(start_day: date, num_days: int, option_map: Dict[str, List[str]]) -> None:
    header_cols = st.columns([0.9] + [1] * num_days)
    with header_cols[0]:
        st.markdown('<div class="meal-grid-spacer"></div>', unsafe_allow_html=True)
    for i in range(num_days):
        current_day = start_day + timedelta(days=i)
        with header_cols[i + 1]:
            st.markdown(f'<div class="day-header">{current_day.strftime("%A")}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="date-header">{current_day.strftime("%m/%d/%Y")}</div>', unsafe_allow_html=True)

    for part in DAY_PARTS:
        row_cols = st.columns([0.9] + [1] * num_days)
        with row_cols[0]:
            st.markdown(f'<div class="row-label">{part}</div>', unsafe_allow_html=True)
        for i in range(num_days):
            key = slot_key(i, part)
            options = option_map[part]
            current_value = st.session_state.get(key, "--")
            if current_value not in options:
                st.session_state[key] = "--"
                current_value = "--"
            with row_cols[i + 1]:
                st.selectbox(part, options, index=options.index(current_value), key=key, label_visibility="collapsed")


def render_mobile_planner(start_day: date, num_days: int, option_map: Dict[str, List[str]]) -> None:
    #st.markdown("<div class='mobile-mode-note'>Mobile mode uses one simple card per day with larger controls.</div>", unsafe_allow_html=True)
    for i in range(num_days):
        current_day = start_day + timedelta(days=i)
        st.markdown("<div class='mobile-day-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='mobile-day-title'>{current_day.strftime('%A')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='mobile-day-date'>{current_day.strftime('%B %d, %Y')}</div>", unsafe_allow_html=True)
        for part in DAY_PARTS:
            key = slot_key(i, part)
            options = option_map[part]
            current_value = st.session_state.get(key, "--")
            if current_value not in options:
                st.session_state[key] = "--"
                current_value = "--"
            st.selectbox(part, options, index=options.index(current_value), key=key, label_visibility="visible")
        st.markdown("</div>", unsafe_allow_html=True)


with selector_tab:
    if st.session_state.get("meal_prep_mode_active", False):
        render_meal_prep_mode()
    elif st.session_state.get("meals_slide_deck_active", False):
        render_meals_slide_deck()
    elif st.session_state.get("directions_view_active", False):
        render_directions_deck(str(st.session_state.get("directions_meal_name", "")))
    else:
        prefs: List[str] = list(st.session_state.get("meal_filter_preference", []))
        times: List[str] = list(st.session_state.get("meal_filter_time", []))
        costs: List[str] = list(st.session_state.get("meal_filter_cost", []))
        fills: List[str] = list(st.session_state.get("meal_filter_fill", []))

        offset_days = int(st.session_state.get("offset_days", 0))
        num_days = max(1, min(31, int(st.session_state.get("num_days", 7))))
        start_day = date.today() + timedelta(days=offset_days)

        breakfast_options = meal_options("Breakfast", prefs, times, costs, fills)
        lunch_options = meal_options("Lunch", prefs, times, costs, fills)
        dinner_options = meal_options("Dinner", prefs, times, costs, fills)

        top_mode_cols = st.columns([1.2, 2.4])
        with top_mode_cols[0]:
            st.toggle("Mobile friendly mode", key="mobile_mode_planner")
        with top_mode_cols[1]:
            st.caption(f"Week starts {start_day.strftime('%A, %b %d, %Y')}.")

        option_map = {"Breakfast": breakfast_options, "Lunch": lunch_options, "Dinner": dinner_options}
        if st.session_state.get("mobile_mode_planner", False):
            render_mobile_planner(start_day, num_days, option_map)
        else:
            render_planner_grid(start_day, num_days, option_map)

        random_col1, random_col2, random_col3 = st.columns(3)
        with random_col1:
            st.button("Add random breakfast", use_container_width=True, on_click=add_random_meal_to_random_day, args=("Breakfast", breakfast_options))
        with random_col2:
            st.button("Add random lunch", use_container_width=True, on_click=add_random_meal_to_random_day, args=("Lunch", lunch_options))
        with random_col3:
            st.button("Add random dinner", use_container_width=True, on_click=add_random_meal_to_random_day, args=("Dinner", dinner_options))

        with st.expander("Optional filters", expanded=False):
            f1, f2, f3, f4 = st.columns(4)
            f1.multiselect("Preference", unique_values("preference"), key="meal_filter_preference")
            f2.multiselect("Time", unique_values("time"), key="meal_filter_time")
            f3.multiselect("Cost", unique_values("cost"), key="meal_filter_cost")
            f4.multiselect("Fill", unique_values("fill"), key="meal_filter_fill")

            custom_filter_keys = custom_columns()
            if custom_filter_keys:
                st.markdown("#### Custom column filters")
                custom_filter_cols = st.columns(min(3, len(custom_filter_keys)))
                all_meals = load_meals()
                for idx, extra in enumerate(custom_filter_keys):
                    options = sorted({str(meal.get(extra, "")).strip() for meal in all_meals if str(meal.get(extra, "")).strip()}, key=str.lower)
                    with custom_filter_cols[idx % len(custom_filter_cols)]:
                        st.multiselect(extra.replace("_", " ").title(), options, key=f"meal_filter_custom_{extra}")

        control_gap_open = "<div class='mobile-control-stack'>" if st.session_state.get("mobile_mode_planner", False) else ""
        control_gap_close = "</div>" if st.session_state.get("mobile_mode_planner", False) else ""
        st.markdown(control_gap_open, unsafe_allow_html=True)
        controls1, controls1b, controls2, controls3, controls4 = st.columns([1, 1, 1, 1, 1])
        with controls1:
            st.number_input("Offset (days)", min_value=0, max_value=365, step=1, key="offset_days")
        with controls1b:
            st.number_input("Number of days", min_value=1, max_value=31, step=1, key="num_days")
        with controls2:
            st.write("")
            st.button("Clear week", use_container_width=True, on_click=clear_schedule)
        with controls3:
            st.write("")
            if st.button("Save current meals", use_container_width=True):
                save_current_schedule()
                st.success("Current meals saved.")
        with controls4:
            st.write("")
            st.button("Safe close down", use_container_width=True, on_click=safe_close_down)
        st.markdown(control_gap_close, unsafe_allow_html=True)

        if st.session_state.get("safe_close_requested", False):
            st.success("Meals and weekly settings were saved. You can now close this browser tab and stop the Streamlit app from your terminal.")


        row1, row2 = st.columns([1.2, 1])
        with row1:
            st.checkbox("Include standard weekly items", key="include_standard_weekly")

        with row2:
            if st.button("Save standard weekly items", use_container_width=True):
                save_settings(
                    bool(st.session_state.get("include_standard_weekly", False)),
                    str(st.session_state.get("standard_weekly_items", "")),
                )
                st.success("Saved")

        st.text_area(
            "",
            key="standard_weekly_items",
            height=100,
            placeholder="Milk\nEggs\nBread",
        )


        chosen = selected_meals()
        items = grocery_items(chosen, include_standard_weekly=bool(st.session_state.get("include_standard_weekly", False)), standard_weekly_items=str(st.session_state.get("standard_weekly_items", "")))
        standard_items = set(parse_standard_weekly_items(str(st.session_state.get("standard_weekly_items", ""))))
        grocery_rows = []
        for ingredient in items:
            item_type = "Standard Weekly" if ingredient in standard_items else "Meal Ingredient"
            checked = bool(st.session_state.get(f"ingredient_{ingredient}", False))
            grocery_rows.append({"Ingredient": ingredient, "Picked Up": checked, "Type": item_type})

        meal_csv = csv_bytes_for_meals(start_day, dinner_only=False)
        dinner_csv = csv_bytes_for_meals(start_day, dinner_only=True)
        printable_html_text = weekly_plan_html(start_day, title="JD's Weekly Meal Plan")
        printable_html = printable_html_text.encode("utf-8")

        section_divider(2, "1rem 0 0.8rem 0")
        st.subheader("Grocery list")
        if not items:
            st.info("Pick some meals or add standard weekly items to generate a grocery list.")
        else:
            grocery_cols = st.columns(4)
            for idx, ingredient in enumerate(items):
                with grocery_cols[idx % 4]:
                    st.checkbox(ingredient, key=f"ingredient_{ingredient}")
            grocery_rows = []
            for ingredient in items:
                item_type = "Standard Weekly" if ingredient in standard_items else "Meal Ingredient"
                grocery_rows.append({"Ingredient": ingredient, "Picked Up": bool(st.session_state.get(f"ingredient_{ingredient}", False)), "Type": item_type})

        empty_csv = pd.DataFrame(columns=["Ingredient", "Picked Up", "Type"]).to_csv(index=False).encode("utf-8")
        grocery_csv = pd.DataFrame(grocery_rows).to_csv(index=False).encode("utf-8") if grocery_rows else empty_csv

        download_cols = st.columns(4)
        with download_cols[0]:
            st.download_button("Download grocery list (.csv)", grocery_csv, file_name="grocery_list.csv", mime="text/csv", use_container_width=True)
        with download_cols[1]:
            st.download_button("Download full meal calendar (.csv)", meal_csv, file_name="meal_calendar.csv", mime="text/csv", use_container_width=True)
        with download_cols[2]:
            st.download_button("Download dinners only (.csv)", dinner_csv, file_name="dinner_calendar.csv", mime="text/csv", use_container_width=True)
        with download_cols[3]:
            st.download_button("Download 8.5x11 weekly meal sheet (.html)", printable_html, file_name="weekly_meal_sheet.html", mime="text/html", help="Open in a browser and print to Letter size.", use_container_width=True)

        with st.expander("Preview printable theme", expanded=False):
            st.components.v1.html(printable_html_text, height=700, scrolling=True)

        section_divider(2, "1rem 0 0.8rem 0")
        st.subheader("Ingredients by meal")
        if not chosen:
            st.info("Pick some meals to see each meal's ingredient list.")
        else:
            seen = set()
            tile_html = ['<div class="ingredient-tiles">']
            direction_meal_names = []
            lookup_map = meal_lookup()
            for meal in chosen:
                meal_name = meal.get("description", "").strip()
                if not meal_name or meal_name in seen:
                    continue
                seen.add(meal_name)
                ingredients = filtered_display_ingredients(meal.get("ingredients", []))
                if ingredients:
                    ingredient_markup = '<ul class="ingredient-list">' + ''.join(f'<li>{escape(item)}</li>' for item in ingredients) + '</ul>'
                else:
                    ingredient_markup = '<div class="ingredient-empty">No ingredients listed.</div>'
                tile_html.append(f'<div class="ingredient-card"><div class="ingredient-title">{escape(meal_name)}</div>{ingredient_markup}</div>')
                if parse_direction_steps(lookup_map.get(meal_name, {}).get("directions", "")):
                    direction_meal_names.append(meal_name)
            tile_html.append("</div>")
            st.markdown("".join(tile_html), unsafe_allow_html=True)

            st.subheader("Directions Slides")
            slide_button_names = ["Open meals slide deck"] + direction_meal_names
            if len(slide_button_names) == 1:
                st.button("Open meals slide deck", use_container_width=True, on_click=open_meals_slide_deck, key="open_meals_slide_deck_button")
                st.info("Add directions to a meal in the Meal Library to use the direction slide deck view.")
            else:
                button_cols = st.columns(min(4, len(slide_button_names)))
                with button_cols[0]:
                    st.button("Open meals slide deck", use_container_width=True, on_click=open_meals_slide_deck, key="open_meals_slide_deck_button")
                for idx, meal_name in enumerate(direction_meal_names, start=1):
                    with button_cols[idx % len(button_cols)]:
                        st.button(meal_name, key=f"open_directions_{meal_name}", use_container_width=True, on_click=open_directions_deck, args=(meal_name,))

with multiplier_tab:
    render_meal_multiplier_tab()

with prep_tab:
    render_meal_prep_tab()

with library_tab:
    mobile_mode_library = st.toggle("Mobile friendly mode", key="mobile_mode_library")
    if mobile_mode_library:
        action_col1, action_col2, action_col3, action_col4 = st.columns(1), st.columns(1), st.columns(1), st.columns(1)
        action_col1, action_col2, action_col3, action_col4 = action_col1[0], action_col2[0], action_col3[0], action_col4[0]
    else:
        action_col1, action_col2, action_col3, action_col4 = st.columns(4)
    with action_col1:
        if st.button("Add New Meal", use_container_width=True):
            st.session_state.show_add_meal = not st.session_state.show_add_meal
            if st.session_state.show_add_meal:
                st.session_state.show_edit_meal = False
    with action_col2:
        if st.button("Edit Meal", use_container_width=True):
            st.session_state.show_edit_meal = not st.session_state.show_edit_meal
            if st.session_state.show_edit_meal:
                st.session_state.show_add_meal = False
    with action_col3:
        with st.popover("Delete Meal", use_container_width=True):
            meal_names = sorted([meal.get("description", "") for meal in load_meals() if meal.get("description")], key=str.lower)
            delete_name = st.selectbox("Choose meal", ["--"] + meal_names, key="delete_meal_name")
            if st.button("Delete selected meal", use_container_width=True):
                ok, msg = delete_meal_by_name(delete_name if delete_name != "--" else "")
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)
    with action_col4:
        with st.popover("Import / Export Meals", use_container_width=True):
            meal_names = sorted([meal.get("description", "") for meal in load_meals() if meal.get("description")], key=str.lower)
            export_names = st.multiselect(
                "Meals to export",
                meal_names,
                default=meal_names,
                key="meal_export_names",
                help="Choose one or more meals to export into a single zip bundle.",
            )
            export_bundle = build_meal_export_bundle(export_names) if export_names else b""
            st.download_button(
                "Export selected meals",
                data=export_bundle,
                file_name="meal_export_bundle.zip",
                mime="application/zip",
                use_container_width=True,
                disabled=not bool(export_names),
            )
            st.caption("Import one or more .zip bundles or .json meal files. Multiple imports can be uploaded at once.")
            duplicate_mode = st.selectbox(
                "When a meal already exists",
                ["Skip duplicates", "Replace existing meals"],
                key="meal_import_duplicate_mode",
            )
            import_files = st.file_uploader(
                "Import meals",
                type=["zip", "json"],
                accept_multiple_files=True,
                key="meal_import_files",
            )
            if st.button("Import selected files", use_container_width=True, key="meal_import_button"):
                added, replaced, skipped, errors = import_meal_files(
                    import_files,
                    duplicate_mode="replace" if duplicate_mode == "Replace existing meals" else "skip",
                )
                if added or replaced:
                    st.success(f"Imported meals: {added} added, {replaced} replaced, {skipped} skipped.")
                    if errors:
                        for error in errors:
                            st.warning(error)
                    st.rerun()
                elif errors:
                    for error in errors:
                        st.warning(error)
                else:
                    st.info(f"No meals imported. {skipped} skipped.")
    if not st.session_state.show_add_meal and not st.session_state.show_edit_meal:
        with st.expander("Add custom column", expanded=False):
            new_column_name = st.text_input("New column name", placeholder="Spice level")
            st.caption("Examples: spice, meat type, vegan, prep time.")
            if st.button("Add column to meal library", use_container_width=True):
                ok, msg = add_custom_column(new_column_name)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    if st.session_state.show_add_meal:
        st.markdown("### Add New Meal")
        new_form = render_meal_form(mode="add")
        col_save, col_cancel = st.columns(2)
        with col_save:
            if st.button("Save Meal", use_container_width=True):
                new_meal = new_form["meal"]
                if not new_meal.get("description", "").strip():
                    st.warning("Meal name is required")
                else:
                    meals = load_meals()
                    existing_names = {meal.get("description", "") for meal in meals}
                    if new_meal["description"] in existing_names:
                        st.warning("A meal with that name already exists.")
                    else:
                        meals.append(finalize_meal_with_media(new_meal, new_form))
                        save_meals(meals)
                        st.success("Meal added!")
                        st.session_state.show_add_meal = False
                        st.rerun()
        with col_cancel:
            if st.button("Cancel Add", use_container_width=True):
                st.session_state.show_add_meal = False
                st.rerun()

    if st.session_state.show_edit_meal:
        st.markdown("### Edit Existing Meal")
        meal_names = sorted([meal.get("description", "") for meal in load_meals() if meal.get("description")], key=str.lower)
        selected_name = st.selectbox("Choose meal to edit", ["--"] + meal_names, key="edit_meal_name_selector")
        if selected_name == "--":
            st.info("Choose a meal to edit.")
        else:
            current_meal = meal_lookup().get(selected_name, {})
            edit_form = render_meal_form(mode="edit", meal=current_meal)
            col_update, col_cancel = st.columns(2)
            with col_update:
                if st.button("Save Changes", use_container_width=True):
                    edited_meal = finalize_meal_with_media(edit_form["meal"], edit_form, existing_meal=current_meal)
                    ok, msg = update_meal(selected_name, edited_meal)
                    if ok:
                        st.success(msg)
                        st.session_state.show_edit_meal = False
                        st.rerun()
                    else:
                        st.warning(msg)
            with col_cancel:
                if st.button("Cancel Edit", use_container_width=True):
                    st.session_state.show_edit_meal = False
                    st.rerun()
    if not st.session_state.show_add_meal and not st.session_state.show_edit_meal:
        search = st.text_input("Search meals")
        table = meal_table().copy()
        if search:
            needle = search.lower().strip()
            table = table[table.apply(lambda row: any(needle in str(value).lower() for value in row), axis=1)]

        st.dataframe(
            table.style.set_properties(**{"white-space": "normal", "word-break": "break-word"}),
            use_container_width=True,
            hide_index=True,
            height=560,
        )
        st.caption(f"{len(table)} meals in view")

