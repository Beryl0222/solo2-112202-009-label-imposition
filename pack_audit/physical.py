"""印面层级、物理持久性和叠贴后可见文本。"""
from __future__ import annotations

import re
from typing import Any

from .textfacts import extract_statement

BASE_BOX_RE = re.compile(r"底盒|盒胚|外盒|纸盒|base|box|caja", re.IGNORECASE)
CARD_RE = re.compile(r"内卡|卡片|说明卡|card|tarjeta", re.IGNORECASE)
LABEL_RE = re.compile(r"价签|价格贴|贴纸|标签|短签|model|label|sticker|etiqueta", re.IGNORECASE)
PATCH_NAME_RE = re.compile(r"补|贴|标|patch|sticker|label", re.IGNORECASE)


def parse_id_list(value: str) -> list[str]:
    return [part for part in (value or "").split("|") if part]


def physical_profile(row: dict[str, str]) -> dict[str, Any]:
    removable_value = row.get("removable", "") or ""
    folded = removable_value.strip().casefold()

    if folded in {"否", "no", "false", "0", "permanent"}:
        removable = False
    elif folded in {"是", "yes", "true", "1", "removable"}:
        removable = True
    else:
        removable = bool(re.search(r"可揭|可撕|移除|remov|peel", removable_value, re.IGNORECASE))

    if re.search(r"开盒|开箱|opening|open[- ]?box|unbox", removable_value, re.IGNORECASE):
        visible_stage = "opening"
    elif re.search(r"付款|购买|收银|payment|purchase|checkout", removable_value, re.IGNORECASE):
        visible_stage = "purchase"
    elif removable:
        visible_stage = "unknown_removal"
    else:
        visible_stage = "display"

    sku = row.get("sku", "")
    covers = parse_id_list(row.get("covers", ""))
    if BASE_BOX_RE.search(sku) and not CARD_RE.search(sku):
        kind = "base_box"
    elif CARD_RE.search(sku):
        kind = "insert_card"
    elif LABEL_RE.search(sku) or PATCH_NAME_RE.search(sku) or covers:
        kind = "sticker_or_label"
    else:
        kind = "print_area"

    return {
        "id": row["id"],
        "kind": kind,
        "layer": int(row["layer"]),
        "removable": removable,
        "removable_text": removable_value,
        "visible_stage": visible_stage,
        "permanent_outer": (not removable and visible_stage != "opening"),
        "covers": covers,
    }


def build_surface_index(tables: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in tables["print_surfaces.tsv"]:
        profile = physical_profile(row)
        statement = extract_statement(row["text"])
        index[row["id"]] = {"row": row, **profile, "statement": statement}
    return index


def hidden_surface_ids(surface_ids: list[str], surfaces: dict[str, dict[str, Any]]) -> set[str]:
    return set(hidden_coverage(surface_ids, surfaces).keys())


def hidden_coverage(surface_ids: list[str], surfaces: dict[str, dict[str, Any]]) -> dict[str, str]:
    """返回被覆盖区域 -> 最上层覆盖物 id。"""
    active = set(surface_ids)
    hidden: dict[str, str] = {}
    for covered_id in active:
        covered = surfaces.get(covered_id)
        if not covered:
            continue
        coverers = []
        for other_id in active:
            other = surfaces.get(other_id)
            if not other or other_id == covered_id:
                continue
            if covered_id in other["covers"] and other["layer"] > covered["layer"]:
                coverers.append(other)
        if coverers:
            top = max(coverers, key=lambda item: item["layer"])
            hidden[covered_id] = top["id"]
    return hidden


def visible_surface_ids(surface_ids: list[str], surfaces: dict[str, dict[str, Any]]) -> list[str]:
    hidden = hidden_surface_ids(surface_ids, surfaces)
    return [sid for sid in surface_ids if sid not in hidden]


def collated_text(surface_ids: list[str], surfaces: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """返回叠贴后仍可见的文字，按层级从低到高排列。"""
    visible = visible_surface_ids(surface_ids, surfaces)
    return [
        {"id": sid, "layer": surfaces[sid]["layer"], "text": surfaces[sid]["row"]["text"]}
        for sid in sorted(visible, key=lambda sid: surfaces[sid]["layer"])
    ]
