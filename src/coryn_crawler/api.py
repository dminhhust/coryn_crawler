from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Settings
from .http import CorynHttpClient
from .storage import load_json, load_jsonl, save_json, save_jsonl

log = logging.getLogger(__name__)

ENDPOINTS = {
    "items": "items.php",
    "monsters": "monsters.php",
    "maps": "maps.php",
}


class CorynCrawler:
    def __init__(self, settings: Settings, client: CorynHttpClient, root: Path):
        self.settings = settings
        self.client = client
        self.root = root
        self.raw_dir = root / "raw"
        self.detail_dir = self.raw_dir / "details"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.detail_dir.mkdir(parents=True, exist_ok=True)

    def crawl_collection(self, resource: str, resume: bool = True) -> list[dict[str, Any]]:
        endpoint = ENDPOINTS[resource]
        out_file = self.raw_dir / f"{resource}.jsonl"
        state_file = self.raw_dir / f".{resource}.state.json"

        rows = load_jsonl(out_file) if resume else []
        seen_ids = {row.get("id") for row in rows if row.get("id") is not None}
        state = load_json(state_file, {}) if resume else {}
        offset = int(state.get("offset", len(rows)))
        total = state.get("total")

        # If an existing file is complete, use it directly.
        if total is not None and offset >= int(total):
            log.info("%s collection already complete: %s records", resource, len(rows))
            return rows

        while total is None or offset < int(total):
            payload = self.client.get_json(
                endpoint,
                {"limit": self.settings.page_size, "offset": offset},
            )
            data = payload.get("data", [])
            meta = payload.get("meta") or {}

            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                raise ValueError(f"Unexpected data shape for {resource}: {type(data)!r}")

            if total is None and meta.get("total") is not None:
                total = int(meta["total"])
                log.info("%s total reported by API: %s", resource, total)

            if not data:
                log.info("No more %s returned at offset %s", resource, offset)
                break

            added = 0
            for row in data:
                rid = row.get("id") if isinstance(row, dict) else None
                if rid is None or rid not in seen_ids:
                    rows.append(row)
                    if rid is not None:
                        seen_ids.add(rid)
                    added += 1

            offset += len(data)
            save_jsonl(out_file, rows)
            save_json(state_file, {"offset": offset, "total": total})
            log.info(
                "%s: offset=%s total=%s rows_saved=%s (+%s)",
                resource,
                offset,
                total if total is not None else "?",
                len(rows),
                added,
            )

            if len(data) < self.settings.page_size:
                break

        save_json(state_file, {"offset": offset, "total": total or len(rows)})
        return rows

    def crawl_details(
        self,
        resource: str,
        rows: list[dict[str, Any]],
        resume: bool = True,
    ) -> list[dict[str, Any]]:
        if resource not in {"items", "monsters", "maps"}:
            raise ValueError(resource)

        endpoint = ENDPOINTS[resource]
        folder = self.detail_dir / resource
        folder.mkdir(parents=True, exist_ok=True)
        details: list[dict[str, Any]] = []

        for index, row in enumerate(rows, start=1):
            rid = row.get("id")
            if rid is None:
                log.warning("Skipping %s row without id: %r", resource, row)
                continue

            detail_path = folder / f"{rid}.json"
            if resume and detail_path.exists():
                detail = load_json(detail_path)
            else:
                payload = self.client.get_json(endpoint, {"id": rid})
                detail = payload.get("data")
                if not isinstance(detail, dict):
                    log.warning("Unexpected detail for %s id=%s; skipping", resource, rid)
                    continue
                save_json(detail_path, detail)

            details.append(detail)
            if index == 1 or index % 100 == 0 or index == len(rows):
                log.info("%s details: %s/%s", resource, index, len(rows))

        save_jsonl(self.raw_dir / f"{resource}_details.jsonl", details)
        return details
