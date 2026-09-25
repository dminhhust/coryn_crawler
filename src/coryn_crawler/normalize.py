from __future__ import annotations

from typing import Any


def normalize_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    item_rows: list[dict[str, Any]] = []
    stat_rows: list[dict[str, Any]] = []

    for item in items:
        meta = item.get("meta") or {}
        item_rows.append(
            {
                "item_id": item.get("id"),
                "name": item.get("name"),
                "type_id": item.get("type_id"),
                "type_label": item.get("type_label"),
                "sell": item.get("sell"),
                "process": item.get("process"),
                "process_amount": item.get("process_amount"),
                "badge": meta.get("badge"),
                "note": meta.get("note"),
            }
        )
        for stat in item.get("stats") or []:
            stat_rows.append(
                {
                    "item_id": item.get("id"),
                    "item_name": item.get("name"),
                    "effect_id": stat.get("effect_id"),
                    "effect_name": stat.get("effect_name"),
                    "amount": stat.get("amount"),
                    "applies_to": stat.get("applies_to"),
                }
            )

    return item_rows, stat_rows


def normalize_monsters(monsters: list[dict[str, Any]]) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    monster_rows: list[dict[str, Any]] = []
    boss_rows: list[dict[str, Any]] = []
    drop_rows: list[dict[str, Any]] = []

    for monster in monsters:
        meta = monster.get("meta") or {}
        row = {
            "monster_id": monster.get("id"),
            "name": monster.get("name"),
            "level": monster.get("level"),
            "map_id": monster.get("map_id"),
            "map_name": monster.get("map_name"),
            "type_code": monster.get("type_code"),
            "type_label": monster.get("type_label"),
            "mode": monster.get("mode"),
            "hp": monster.get("hp"),
            "exp": monster.get("exp"),
            "element_id": monster.get("element_id"),
            "element_label": monster.get("element_label"),
            "tameable": monster.get("tameable"),
            "limited": monster.get("limited"),
            "badge": meta.get("badge"),
            "note": meta.get("note"),
        }
        monster_rows.append(row)

        type_label = str(monster.get("type_label") or "").strip().lower()
        if "boss" in type_label:
            boss_rows.append(dict(row))

        for drop in monster.get("drops") or []:
            drop_rows.append(
                {
                    "monster_id": monster.get("id"),
                    "monster_name": monster.get("name"),
                    "monster_type": monster.get("type_label"),
                    "monster_level": monster.get("level"),
                    "monster_mode": monster.get("mode"),
                    "map_id": monster.get("map_id"),
                    "map_name": monster.get("map_name"),
                    "item_id": drop.get("id"),
                    "item_name": drop.get("name"),
                    "item_type_id": drop.get("type_id"),
                    "item_type_label": drop.get("type_label"),
                }
            )

    return monster_rows, boss_rows, drop_rows


def normalize_maps(maps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "map_id": m.get("id"),
            "name": m.get("name"),
            "monster_count": m.get("monster_count"),
        }
        for m in maps
    ]


def make_map_monsters(monsters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for monster in monsters:
        if monster.get("map_id") is None:
            continue
        rows.append(
            {
                "map_id": monster.get("map_id"),
                "map_name": monster.get("map_name"),
                "monster_id": monster.get("id"),
                "monster_name": monster.get("name"),
                "level": monster.get("level"),
                "type_label": monster.get("type_label"),
                "mode": monster.get("mode"),
            }
        )
    return rows
