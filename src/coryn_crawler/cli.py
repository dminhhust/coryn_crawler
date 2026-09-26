from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .api import CorynCrawler
from .config import Settings
from .exporters import export_all
from .http import CorynHttpClient
from .images import ItemImageCrawler
from .offline import build_offline_dataset
from .storage import ensure_dirs, load_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Coryn Club item/monster/map data and item images")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="Crawl one API resource or all API resources")
    crawl.add_argument("resource", choices=["items", "monsters", "maps", "all"])
    crawl.add_argument(
        "--details",
        action="store_true",
        help="Fetch one ID detail per record (needed for complete item stats / monster drops)",
    )
    crawl.add_argument("--no-resume", action="store_true", help="Ignore cached collection/detail files")

    images = sub.add_parser("images", help="Crawl and download the main image for every item HTML page")
    images.add_argument("--no-resume", action="store_true", help="Revisit pages even when an image/no-image result is cached")
    images.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N items (useful for a smoke test)",
    )

    offline = sub.add_parser("offline", help="Build a self-contained offline dataset from crawled data/images")
    offline.add_argument(
        "--zip",
        action="store_true",
        help="Also create data/coryn-offline-dataset.zip for easy transfer",
    )
    offline.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not delete the existing data/offline folder before rebuilding",
    )

    export = sub.add_parser("export", help="Create normalized CSV files from crawled API data")
    export.add_argument(
        "--prefer-details",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prefer *_details.jsonl when present (default: true)",
    )

    full = sub.add_parser("full", help="Crawl all API data, optionally item images, then export CSVs")
    full.add_argument("--no-resume", action="store_true")
    full.add_argument(
        "--with-images",
        action="store_true",
        help="Also visit every item HTML page and download its main image",
    )
    full.add_argument(
        "--image-limit",
        type=int,
        default=None,
        help="With --with-images, process only the first N items",
    )
    full.add_argument(
        "--offline-ready",
        action="store_true",
        help="Download item images and build data/offline after crawling/exporting",
    )
    full.add_argument(
        "--offline-zip",
        action="store_true",
        help="With --offline-ready, also create data/coryn-offline-dataset.zip",
    )

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


def _crawl_images(
    settings: Settings,
    client: CorynHttpClient,
    crawler: CorynCrawler,
    *,
    resume: bool,
    limit: int | None,
) -> None:
    items = _load_resource(settings.output_dir, "items", prefer_details=False)
    if not items:
        items = crawler.crawl_collection("items", resume=resume)
    image_crawler = ItemImageCrawler(settings, client, settings.output_dir)
    results = image_crawler.crawl(items, resume=resume, limit=limit)
    downloaded = sum(result.status == "downloaded" for result in results)
    no_image = sum(result.status == "no_image" for result in results)
    errors = sum(result.status == "error" for result in results)
    print(f"\nImage index: {(settings.output_dir / 'processed' / 'item_images.csv').resolve()}")
    print(f"Images folder: {(settings.output_dir / 'images' / 'items').resolve()}")
    print(f"Indexed results: {len(results):,} (downloaded={downloaded:,}, no_image={no_image:,}, errors={errors:,})")


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
            if args.details:
                crawler.crawl_details(resource, rows, resume=not args.no_resume)
        print(f"\nRaw data folder: {dirs['raw'].resolve()}")
        return

    if args.command == "images":
        if args.limit is not None and args.limit < 1:
            parser.error("images --limit must be at least 1")
        _crawl_images(
            settings,
            client,
            crawler,
            resume=not args.no_resume,
            limit=args.limit,
        )
        return

    if args.command == "export":
        _export(settings.output_dir, args.prefer_details)
        return

    if args.command == "offline":
        result = build_offline_dataset(
            settings.output_dir,
            make_zip=args.zip,
            clean=not args.no_clean,
        )
        print(f"\nOffline dataset: {result['offline_dir'].resolve()}")
        if result["zip_path"] is not None:
            print(f"Offline ZIP: {result['zip_path'].resolve()}")
        print(f"Images copied: {result['counts']['images_copied']:,}")
        missing = result["missing_local_images_marked_downloaded"]
        if missing:
            print(f"WARNING: {missing:,} image index rows were marked downloaded but the local file was missing.")
        return

    if args.command == "full":
        if args.image_limit is not None and args.image_limit < 1:
            parser.error("full --image-limit must be at least 1")
        resume = not args.no_resume
        items = crawler.crawl_collection("items", resume=resume)
        monsters = crawler.crawl_collection("monsters", resume=resume)
        crawler.crawl_collection("maps", resume=resume)

        crawler.crawl_details("items", items, resume=resume)
        crawler.crawl_details("monsters", monsters, resume=resume)
        _export(settings.output_dir, prefer_details=True)

        if args.with_images or args.offline_ready:
            image_crawler = ItemImageCrawler(settings, client, settings.output_dir)
            image_crawler.crawl(items, resume=resume, limit=args.image_limit)
            print(f"\nItem images: {(settings.output_dir / 'images' / 'items').resolve()}")
            print(f"Image index: {(settings.output_dir / 'processed' / 'item_images.csv').resolve()}")

        if args.offline_ready:
            offline_result = build_offline_dataset(
                settings.output_dir,
                make_zip=args.offline_zip,
                clean=True,
            )
            print(f"Offline dataset: {offline_result['offline_dir'].resolve()}")
            if offline_result["zip_path"] is not None:
                print(f"Offline ZIP: {offline_result['zip_path'].resolve()}")
        return


if __name__ == "__main__":
    main()
