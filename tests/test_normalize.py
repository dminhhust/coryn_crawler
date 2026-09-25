from coryn_crawler.normalize import normalize_items, normalize_monsters, normalize_maps, make_map_monsters


def test_normalize_item_stats():
    items = [{
        "id": 8416,
        "name": "Myco Hat",
        "type_id": 6,
        "type_label": "[Additional]",
        "sell": 1,
        "process": 1,
        "process_amount": 1,
        "meta": {"badge": "White Day 2026", "note": "x"},
        "stats": [{"effect_id": 1, "effect_name": "Base DEF", "amount": 72, "applies_to": 0}],
    }]
    rows, stats = normalize_items(items)
    assert rows[0]["item_id"] == 8416
    assert stats[0]["effect_name"] == "Base DEF"
    assert stats[0]["amount"] == 72


def test_normalize_boss_and_drops():
    monsters = [{
        "id": 3348,
        "name": "Mycodian",
        "level": 240,
        "map_id": 653,
        "map_name": "Ancient Exhibition Grounds",
        "type_code": "B",
        "type_label": "Boss",
        "mode": "Normal",
        "hp": -1,
        "exp": -1,
        "element_id": 4,
        "element_label": "Earth",
        "tameable": False,
        "limited": True,
        "meta": {"badge": "White Day 2026", "note": "event boss"},
        "drops": [{"id": 8376, "name": "Chocolate Sprinkles", "type_id": 14, "type_label": "[Material]"}],
    }]
    all_rows, bosses, drops = normalize_monsters(monsters)
    assert len(all_rows) == 1
    assert len(bosses) == 1
    assert drops[0]["item_id"] == 8376
    assert drops[0]["map_id"] == 653


def test_maps_and_map_monsters():
    maps = [{"id": 653, "name": "Ancient Exhibition Grounds", "monster_count": 3}]
    monsters = [{"id": 3348, "name": "Mycodian", "level": 240, "map_id": 653, "map_name": "Ancient Exhibition Grounds", "type_label": "Boss", "mode": "Normal"}]
    assert normalize_maps(maps)[0]["monster_count"] == 3
    assert make_map_monsters(monsters)[0]["monster_id"] == 3348
