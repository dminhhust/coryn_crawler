from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

PREFIX_RE = re.compile(r"^(\d+)_(.+)$")
TAIL_RE = re.compile(r"^(.+)_([0-9]+)(\.[^.]+)$")


def stripped_name(name: str) -> str | None:
    """Return filename without a leading '<digits>_' prefix."""
    match = PREFIX_RE.match(name)
    return match.group(2) if match else None


def canonical_image_name(name: str) -> str:
    """
    Return the canonical object image name.

    Both crawler ID prefixes and duplicate suffixes are removed:

        8571_reindeer_antlers.png -> reindeer_antlers.png
        reindeer_antlers_2.png     -> reindeer_antlers.png
        8571_reindeer_antlers_2.png -> reindeer_antlers.png

    Only a trailing ``_<number>`` immediately before the extension is treated
    as a duplicate suffix.
    """
    clean = stripped_name(name) or name
    match = TAIL_RE.match(clean)
    if match:
        clean = f"{match.group(1)}{match.group(3)}"
    return clean


def build_dedupe_plan(image_dir: Path) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    """
    Return ``(renames, duplicate_removals)`` without changing files.

    Leading ID prefixes and trailing duplicate suffixes are canonicalized to
    the same object name. For example::

        1_hat.png   -> hat.png
        2_hat.png   -> removed
        hat_2.png   -> removed
        hat_3.png   -> removed
        9_hat_2.png -> removed

    If ``hat.png`` already exists, it is always kept. Otherwise exactly one
    alias is renamed to ``hat.png`` and the rest are removed. No numbered
    suffixes are created.
    """
    renames: list[tuple[Path, Path]] = []
    removals: list[tuple[Path, Path]] = []

    if not image_dir.exists():
        return renames, removals

    files = sorted(path for path in image_dir.iterdir() if path.is_file())
    existing_names = {path.name for path in files}
    by_canonical_name: dict[str, list[Path]] = {}

    for path in files:
        canonical = canonical_image_name(path.name)
        if canonical != path.name:
            by_canonical_name.setdefault(canonical, []).append(path)

    def source_rank(path: Path) -> tuple[int, int, str]:
        # Keep the choice deterministic when no already-clean file exists.
        # Prefer the lowest leading object ID first, matching the old script's
        # behavior. Then prefer the lowest trailing duplicate number.
        prefix = PREFIX_RE.match(path.name)
        if prefix:
            return (0, int(prefix.group(1)), path.name)

        tail = TAIL_RE.match(path.name)
        if tail:
            return (1, int(tail.group(2)), path.name)

        return (2, 2**63 - 1, path.name)

    for canonical_name, aliases in sorted(by_canonical_name.items()):
        canonical_path = image_dir / canonical_name
        aliases.sort(key=source_rank)

        if canonical_name in existing_names:
            # The clean object image already exists. Every numbered alias is
            # redundant and may be removed.
            for src in aliases:
                removals.append((src, canonical_path))
            continue

        # No clean image exists. Promote one deterministic alias to the clean
        # canonical name and remove all other aliases of the same object.
        canonical_src = aliases[0]
        renames.append((canonical_src, canonical_path))
        for src in aliases[1:]:
            removals.append((src, canonical_path))

    return renames, removals


def _replace_path_text(value: str, replacements: dict[str, str]) -> str:
    normalized = value.replace("\\", "/")
    for old, new in replacements.items():
        if normalized == old:
            return new
        if normalized.endswith("/" + old):
            return normalized[: -len(old)] + new
    return value


def update_csv(path: Path, replacements: dict[str, str], path_fields: set[str], dry_run: bool) -> int:
    if not path.exists():
        return 0

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    changed = 0
    for row in rows:
        for field in path_fields:
            if field not in row or not row[field]:
                continue
            new_value = _replace_path_text(row[field], replacements)
            if new_value != row[field]:
                row[field] = new_value
                changed += 1

    if changed and not dry_run:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return changed


def _rewrite_json_value(value: Any, replacements: dict[str, str], fields: set[str] | None = None) -> tuple[Any, int]:
    changed = 0

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str) and (fields is None or key in fields):
                new_item = _replace_path_text(item, replacements)
                if new_item != item:
                    changed += 1
                out[key] = new_item
            else:
                out[key], nested = _rewrite_json_value(item, replacements, fields)
                changed += nested
        return out, changed

    if isinstance(value, list):
        out_list = []
        for item in value:
            new_item, nested = _rewrite_json_value(item, replacements, fields)
            out_list.append(new_item)
            changed += nested
        return out_list, changed

    return value, 0


def update_json(path: Path, replacements: dict[str, str], path_fields: set[str], dry_run: bool) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0

    new_payload, changed = _rewrite_json_value(payload, replacements, path_fields)
    if changed and not dry_run:
        path.write_text(json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def update_jsonl(path: Path, replacements: dict[str, str], path_fields: set[str], dry_run: bool) -> int:
    if not path.exists():
        return 0

    rows: list[Any] = []
    changed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            rows.append(line)
            continue
        new_payload, nested = _rewrite_json_value(payload, replacements, path_fields)
        changed += nested
        rows.append(new_payload)

    if changed and not dry_run:
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                if isinstance(row, str):
                    f.write(row + "\n")
                else:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return changed


def update_references(root: Path, replacements: dict[str, str], dry_run: bool) -> int:
    """Update the crawler's cached/indexed paths after files are renamed."""
    changed = 0
    path_fields = {"local_path", "offline_image_path"}

    changed += update_csv(root / "processed" / "item_images.csv", replacements, path_fields, dry_run)
    changed += update_jsonl(root / "raw" / "item_images.jsonl", replacements, path_fields, dry_run)

    details_dir = root / "raw" / "image_details" / "items"
    if details_dir.exists():
        for path in details_dir.glob("*.json"):
            changed += update_json(path, replacements, path_fields, dry_run)

    # If an offline bundle already exists, update its data references too.
    offline = root / "offline"
    changed += update_csv(offline / "data" / "item_images.csv", replacements, path_fields, dry_run)
    changed += update_csv(offline / "data" / "items_with_images.csv", replacements, path_fields, dry_run)
    changed += update_jsonl(offline / "data" / "items_with_images.jsonl", replacements, path_fields, dry_run)
    changed += update_json(offline / "data" / "catalog.json", replacements, path_fields, dry_run)
    changed += update_jsonl(offline / "raw" / "item_images.jsonl", replacements, path_fields, dry_run)

    return changed


def rename_directory(image_dir: Path, dry_run: bool, skip_collisions: bool = False) -> tuple[int, int, dict[str, str]]:
    """
    Canonicalize numbered item-image filenames.

    Files that collapse to the same clean name are considered the same object.
    One clean file is kept and redundant numbered copies are deleted. Every old
    path is mapped to the canonical clean path so CSV/JSON references remain
    valid.
    """
    renames, removals = build_dedupe_plan(image_dir)

    replacements: dict[str, str] = {}
    renamed = 0
    removed = 0

    for src, dst in renames:
        print(f"{'DRY-RUN ' if dry_run else ''}RENAME: {src.name} -> {dst.name}")
        if not dry_run:
            src.rename(dst)
        replacements[src.as_posix()] = dst.as_posix()
        renamed += 1

    for src, canonical in removals:
        print(
            f"{'DRY-RUN ' if dry_run else ''}DEDUP: {src.name} -> {canonical.name} "
            "(remove duplicate)"
        )
        if not dry_run:
            src.unlink()
        replacements[src.as_posix()] = canonical.as_posix()
        removed += 1

    return renamed, removed, replacements

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonicalize Coryn item images by removing leading ID prefixes and trailing '_<number>' duplicate suffixes."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data"),
        help="Crawler data root (default: data)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without modifying files",
    )
    parser.add_argument(
        "--skip-collisions",
        action="store_true",
        help="Deprecated: collisions are always deduplicated to one clean canonical filename",
    )
    parser.add_argument(
        "--no-update-references",
        action="store_true",
        help="Do not update CSV/JSON/JSONL local image paths",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    source_dir = root / "images" / "items"
    offline_dir = root / "offline" / "images" / "items"

    if not source_dir.exists() and not offline_dir.exists():
        print(f"No item image directory found under: {root}", file=sys.stderr)
        return 1

    all_replacements: dict[str, str] = {}
    total_renamed = 0
    total_removed = 0

    for image_dir in (source_dir, offline_dir):
        if not image_dir.exists():
            continue
        try:
            renamed, removed, raw_replacements = rename_directory(
                image_dir,
                dry_run=args.dry_run,
                skip_collisions=args.skip_collisions,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        total_renamed += renamed
        total_removed += removed

        # Store paths relative to data root so they match crawler index fields.
        for old_abs, new_abs in raw_replacements.items():
            old = Path(old_abs)
            new = Path(new_abs)
            try:
                old_rel = old.relative_to(root).as_posix()
                new_rel = new.relative_to(root).as_posix()
            except ValueError:
                continue
            all_replacements[old_rel] = new_rel

            # Offline tables store paths relative to data/offline.
            if offline_dir in old.parents or old == offline_dir:
                try:
                    all_replacements[old.relative_to(root / "offline").as_posix()] = new.relative_to(
                        root / "offline"
                    ).as_posix()
                except ValueError:
                    pass

    ref_changes = 0
    if not args.no_update_references and all_replacements:
        ref_changes = update_references(root, all_replacements, args.dry_run)

    print()
    print(f"Files {'that would be ' if args.dry_run else ''}renamed: {total_renamed}")
    print(f"Duplicate files {'that would be ' if args.dry_run else ''}removed: {total_removed}")
    print(f"References {'that would be ' if args.dry_run else ''}updated: {ref_changes}")
    if (root / "offline" / "manifest.json").exists() and not args.dry_run:
        print(
            "Note: rebuild the offline manifest/ZIP after renaming with:\n"
            "  coryn-crawl offline --zip"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
