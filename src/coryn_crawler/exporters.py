from __future__ import annotations

from pathlib import Path
from typing import Any

from .normalize import make_map_monsters, normalize_items, normalize_maps, normalize_monsters
from .storage import save_csv

ITEM_FIELDS = [
    "item_id", "name", "type_id", "type_label", "sell", "process", "process_amount", "badge", "note"
]
ITEM_STAT_FIELDS = ["item_id", "item_name", "effect_id", "effect_name", "amount", "applies_to"]
MONSTER_FIELDS = [
    "monster_id", "name", "level", "map_id", "map_name", "type_code", "type_label", "mode",
    "hp", "exp", "element_id", "element_label", "tameable", "limited", "badge", "note"
]
DROP_FIELDS = [
    "monster_id", "monster_name", "monster_type", "monster_level", "monster_mode",
    "map_id", "map_name", "item_id", "item_name", "item_type_id", "item_type_label"
]
MAP_FIELDS = ["map_id", "name", "monster_count"]
MAP_MONSTER_FIELDS = ["map_id", "map_name", "monster_id", "monster_name", "level", "type_label", "mode"]


def export_all(
    processed_dir: Path,
    items: list[dict[str, Any]],
    monsters: list[dict[str, Any]],
    maps: list[dict[str, Any]],
) -> dict[str, int]:
    processed_dir.mkdir(parents=True, exist_ok=True)

    item_rows, item_stats = normalize_items(items)
    monster_rows, boss_rows, drops = normalize_monsters(monsters)
    map_rows = normalize_maps(maps)
    map_monsters = make_map_monsters(monsters)

    save_csv(processed_dir / "items.csv", item_rows, ITEM_FIELDS)
    save_csv(processed_dir / "item_stats.csv", item_stats, ITEM_STAT_FIELDS)
    save_csv(processed_dir / "monsters.csv", monster_rows, MONSTER_FIELDS)
    save_csv(processed_dir / "bosses.csv", boss_rows, MONSTER_FIELDS)
    save_csv(processed_dir / "monster_drops.csv", drops, DROP_FIELDS)
    save_csv(processed_dir / "maps.csv", map_rows, MAP_FIELDS)
    save_csv(processed_dir / "map_monsters.csv", map_monsters, MAP_MONSTER_FIELDS)

    return {
        "items": len(item_rows),
        "item_stats": len(item_stats),
        "monsters": len(monster_rows),
        "bosses": len(boss_rows),
        "monster_drops": len(drops),
        "maps": len(map_rows),
        "map_monsters": len(map_monsters),
    }
