from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import save_csv, save_json


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_offline_dataset(
    root: Path,
    *,
    make_zip: bool = False,
    clean: bool = True,
) -> dict[str, Any]:
    """Build a self-contained offline dataset under ``root/offline``.

    The bundle intentionally uses only relative paths for local assets. Remote
    Coryn URLs are retained only as provenance fields and are never required to
    load the bundled data or images.
    """

    processed = root / "processed"
    offline = root / "offline"
    data_dir = offline / "data"
    raw_dir = offline / "raw"
    image_dir = offline / "images" / "items"

    if clean and offline.exists():
        shutil.rmtree(offline)
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    table_names = [
        "items.csv",
        "item_stats.csv",
        "monsters.csv",
        "bosses.csv",
        "monster_drops.csv",
        "maps.csv",
        "map_monsters.csv",
        "item_images.csv",
    ]

    copied_tables: list[str] = []
    for name in table_names:
        src = processed / name
        if src.exists():
            _copy_file(src, data_dir / name)
            copied_tables.append(name)

    # Preserve consolidated raw API responses as a future-proof fallback.
    raw_names = [
        "items.jsonl",
        "items_details.jsonl",
        "monsters.jsonl",
        "monsters_details.jsonl",
        "maps.jsonl",
        "maps_details.jsonl",
        "item_images.jsonl",
    ]
    copied_raw: list[str] = []
    for name in raw_names:
        src = root / "raw" / name
        if src.exists():
            _copy_file(src, raw_dir / name)
            copied_raw.append(name)

    items = _read_csv(processed / "items.csv")
    image_rows = _read_csv(processed / "item_images.csv")
    image_by_id = {str(row.get("item_id", "")): row for row in image_rows}

    combined: list[dict[str, Any]] = []
    copied_images = 0
    missing_local_images = 0
    unindexed_items = 0
    image_error_items = 0

    for item in items:
        item_id = str(item.get("item_id", ""))
        image = image_by_id.get(item_id, {})
        if not image:
            unindexed_items += 1
        elif image.get("status") == "error":
            image_error_items += 1
        local_rel = str(image.get("local_path", "") or "")
        offline_rel = ""

        if local_rel:
            src = root / local_rel
            if src.exists() and src.is_file():
                dst = image_dir / src.name
                _copy_file(src, dst)
                offline_rel = (Path("images") / "items" / src.name).as_posix()
                copied_images += 1
            elif image.get("status") == "downloaded":
                missing_local_images += 1

        combined.append(
            {
                **item,
                "image_status": image.get("status", "not_crawled"),
                "offline_image_path": offline_rel,
                "image_sha256": image.get("sha256", ""),
                "image_file_size": image.get("file_size", ""),
                "image_width": image.get("width", ""),
                "image_height": image.get("height", ""),
                "image_content_type": image.get("content_type", ""),
                # Source URLs are provenance only; the bundle does not depend on them.
                "source_page_url": image.get("page_url", ""),
                "source_image_url": image.get("image_url", ""),
            }
        )

    combined_fields = [
        "item_id",
        "name",
        "type_id",
        "type_label",
        "sell",
        "process",
        "process_amount",
        "badge",
        "note",
        "image_status",
        "offline_image_path",
        "image_sha256",
        "image_file_size",
        "image_width",
        "image_height",
        "image_content_type",
        "source_page_url",
        "source_image_url",
    ]
    save_csv(data_dir / "items_with_images.csv", combined, combined_fields)
    _write_jsonl(data_dir / "items_with_images.jsonl", combined)

    # Compact JSON catalog for applications that do not want to parse CSV.
    save_json(
        data_dir / "catalog.json",
        {
            "items": combined,
            "maps": _read_csv(processed / "maps.csv"),
            "monsters": _read_csv(processed / "monsters.csv"),
            "bosses": _read_csv(processed / "bosses.csv"),
        },
    )

    # Hash every payload file so corruption can be detected after moving/archive extraction.
    file_entries: list[dict[str, Any]] = []
    for path in sorted(p for p in offline.rglob("*") if p.is_file() and p.name != "manifest.json"):
        rel = path.relative_to(offline).as_posix()
        file_entries.append(
            {
                "path": rel,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    table_counts = {
        "items": len(items),
        "item_stats": len(_read_csv(processed / "item_stats.csv")),
        "monsters": len(_read_csv(processed / "monsters.csv")),
        "bosses": len(_read_csv(processed / "bosses.csv")),
        "monster_drops": len(_read_csv(processed / "monster_drops.csv")),
        "maps": len(_read_csv(processed / "maps.csv")),
        "map_monsters": len(_read_csv(processed / "map_monsters.csv")),
        "image_index": len(image_rows),
        "images_copied": copied_images,
    }

    manifest = {
        "dataset": "Coryn Club offline dataset",
        "format_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline_ready": (
            missing_local_images == 0
            and unindexed_items == 0
            and image_error_items == 0
        ),
        "requires_network": False,
        "description": (
            "Self-contained normalized Coryn Club dataset. Source URLs are retained only "
            "for provenance; consumers should use offline_image_path for item images."
        ),
        "counts": table_counts,
        "missing_local_images_marked_downloaded": missing_local_images,
        "unindexed_items": unindexed_items,
        "image_error_items": image_error_items,
        "tables": copied_tables + ["items_with_images.csv", "items_with_images.jsonl", "catalog.json"],
        "raw_files": copied_raw,
        "files": file_entries,
    }
    save_json(offline / "manifest.json", manifest)

    (offline / "README.txt").write_text(
        "Coryn Club offline dataset\n"
        "==========================\n\n"
        "This folder is self-contained and can be moved to another machine.\n"
        "Use data/items_with_images.csv (or .jsonl) as the main item table.\n"
        "Use the offline_image_path field, which is relative to this folder.\n"
        "Remote source_page_url/source_image_url fields are provenance only.\n"
        "Raw consolidated API responses are preserved under raw/.\n"
        "manifest.json contains row counts and SHA-256 checksums.\n",
        encoding="utf-8",
    )

    # Refresh manifest after README exists, including README but excluding manifest itself.
    file_entries = []
    for path in sorted(p for p in offline.rglob("*") if p.is_file() and p.name != "manifest.json"):
        file_entries.append(
            {
                "path": path.relative_to(offline).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest["files"] = file_entries
    save_json(offline / "manifest.json", manifest)

    zip_path: Path | None = None
    if make_zip:
        zip_path = root / "coryn-offline-dataset.zip"
        tmp_zip = zip_path.with_suffix(".zip.tmp")
        if tmp_zip.exists():
            tmp_zip.unlink()
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in sorted(p for p in offline.rglob("*") if p.is_file()):
                zf.write(path, arcname=(Path("coryn-offline-dataset") / path.relative_to(offline)).as_posix())
        tmp_zip.replace(zip_path)

    return {
        "offline_dir": offline,
        "zip_path": zip_path,
        "counts": table_counts,
        "missing_local_images_marked_downloaded": missing_local_images,
        "unindexed_items": unindexed_items,
        "image_error_items": image_error_items,
        "offline_ready": manifest["offline_ready"],
    }
