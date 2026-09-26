import csv
import json
from pathlib import Path

from coryn_crawler.offline import build_offline_dataset
from coryn_crawler.storage import save_csv


def test_build_offline_dataset_copies_images_and_uses_relative_paths(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir(parents=True)

    save_csv(
        processed / "items.csv",
        [{
            "item_id": 8571,
            "name": "Reindeer Antlers",
            "type_id": 1,
            "type_label": "Additional",
            "sell": 1,
            "process": "",
            "process_amount": "",
            "badge": "",
            "note": "",
        }],
        ["item_id", "name", "type_id", "type_label", "sell", "process", "process_amount", "badge", "note"],
    )
    for filename, fields in {
        "item_stats.csv": ["item_id", "item_name", "effect_id", "effect_name", "amount", "applies_to"],
        "monsters.csv": ["monster_id", "name"],
        "bosses.csv": ["monster_id", "name"],
        "monster_drops.csv": ["monster_id", "item_id"],
        "maps.csv": ["map_id", "name", "monster_count"],
        "map_monsters.csv": ["map_id", "monster_id"],
    }.items():
        save_csv(processed / filename, [], fields)

    image_path = tmp_path / "images" / "items" / "8571_reindeer_antlers.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nexample")

    save_csv(
        processed / "item_images.csv",
        [{
            "item_id": 8571,
            "item_name": "Reindeer Antlers",
            "page_url": "https://coryn.club/item.php?id=8571",
            "image_url": "https://coryn.club/uploads/8571.png",
            "local_path": "images/items/8571_reindeer_antlers.png",
            "content_type": "image/png",
            "sha256": "abc",
            "file_size": 15,
            "width": 100,
            "height": 120,
            "downloaded_at": "2026-09-26T00:00:00+00:00",
            "status": "downloaded",
            "error": "",
        }],
        [
            "item_id", "item_name", "page_url", "image_url", "local_path", "content_type",
            "sha256", "file_size", "width", "height", "downloaded_at", "status", "error",
        ],
    )

    result = build_offline_dataset(tmp_path, make_zip=True)
    offline = tmp_path / "offline"

    assert result["offline_ready"] is True
    assert (offline / "images" / "items" / image_path.name).exists()
    assert (tmp_path / "coryn-offline-dataset.zip").exists()

    with (offline / "data" / "items_with_images.csv").open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["offline_image_path"] == "images/items/8571_reindeer_antlers.png"
    assert row["source_image_url"].startswith("https://coryn.club/")

    manifest = json.loads((offline / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requires_network"] is False
    assert manifest["offline_ready"] is True
    assert manifest["counts"]["images_copied"] == 1
    assert any(entry["path"].endswith("8571_reindeer_antlers.png") for entry in manifest["files"])


def test_offline_manifest_flags_unindexed_items(tmp_path: Path):
    processed = tmp_path / "processed"
    processed.mkdir(parents=True)
    save_csv(
        processed / "items.csv",
        [{"item_id": 1, "name": "A", "type_id": "", "type_label": "", "sell": "", "process": "", "process_amount": "", "badge": "", "note": ""}],
        ["item_id", "name", "type_id", "type_label", "sell", "process", "process_amount", "badge", "note"],
    )

    result = build_offline_dataset(tmp_path)
    assert result["offline_ready"] is False
    assert result["unindexed_items"] == 1
