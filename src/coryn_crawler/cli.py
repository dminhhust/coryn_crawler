from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .api import CorynCrawler
from .config import Settings
from .exporters import export_all
from .http import CorynHttpClient
from .storage import ensure_dirs, load_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Coryn Club's public JSON API")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="Crawl one resource or all resources")
    crawl.add_argument("resource", choices=["items", "monsters", "maps", "all"])
    crawl.add_argument(
        "--details",
        action="store_true",
        help="Fetch one ID detail per record (needed for complete item stats / monster drops)",
    )
    crawl.add_argument("--no-resume", action="store_true", help="Ignore cached collection/detail files")

    export = sub.add_parser("export", help="Create normalized CSV files from crawled data")
    export.add_argument(
        "--prefer-details",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prefer *_details.jsonl when present (default: true)",
    )

    full = sub.add_parser("full", help="Crawl all collections, fetch item+monster details, then export CSVs")
    full.add_argument("--no-resume", action="store_true")

    return parser


def _load_resource(root: Path, resource: str, prefer_details: bool = True):
    raw = root / "raw"
    detail_file = raw / f"{resource}_details.jsonl"
    collection_file = raw / f"{resource}.jsonl"
    if prefer_details and detail_file.exists():
        return load_jsonl(detail_file)
    return load_jsonl(collection_file)


def _export(root: Path, prefer_details: bool = True) -> None:
    items = _load_resource(root, "items", prefer_details)
    monsters = _load_resource(root, "monsters", prefer_details)
    maps = _load_resource(root, "maps", prefer_details)
    counts = export_all(root / "processed", items, monsters, maps)
    print("\nExported:")
    for name, count in counts.items():
        print(f"  {name:16s} {count:,}")
    print(f"\nCSV folder: {(root / 'processed').resolve()}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings = Settings.from_env()
    dirs = ensure_dirs(settings.output_dir)
    client = CorynHttpClient(settings)
    crawler = CorynCrawler(settings, client, settings.output_dir)

    if args.command == "crawl":
        resources = ["items", "monsters", "maps"] if args.resource == "all" else [args.resource]
        for resource in resources:
            rows = crawler.crawl_collection(resource, resume=not args.no_resume)
            # Detailed map calls add little beyond the list, so only honor --details explicitly.
            if args.details:
                crawler.crawl_details(resource, rows, resume=not args.no_resume)
        print(f"\nRaw data folder: {dirs['raw'].resolve()}")
        return

    if args.command == "export":
        _export(settings.output_dir, args.prefer_details)
        return

    if args.command == "full":
        resume = not args.no_resume
        items = crawler.crawl_collection("items", resume=resume)
        monsters = crawler.crawl_collection("monsters", resume=resume)
        maps = crawler.crawl_collection("maps", resume=resume)

        # Complete item stats and monster drop information are available on ID lookups.
        crawler.crawl_details("items", items, resume=resume)
        crawler.crawl_details("monsters", monsters, resume=resume)
        # Maps are already lightweight and complete enough for our normalized map table.
        _export(settings.output_dir, prefer_details=True)
        return


if __name__ == "__main__":
    main()
