from __future__ import annotations

import hashlib
import io
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from PIL import Image

from .config import Settings
from .http import CorynHttpClient
from .storage import load_json, save_csv, save_json, save_jsonl

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"}
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
}

REJECT_WORDS = {
    "logo",
    "favicon",
    "sprite",
    "banner",
    "avatar",
    "mascot",
    "icon",
    "loading",
    "placeholder",
    "advert",
    "social",
}

POSITIVE_WORDS = {
    "item",
    "equipment",
    "preview",
    "main",
    "detail",
    "gallery",
    "image",
    "photo",
    "upload",
}


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    score: int
    source: str
    context: str = ""


@dataclass
class ItemImageResult:
    item_id: int
    item_name: str
    page_url: str
    image_url: str = ""
    local_path: str = ""
    content_type: str = ""
    sha256: str = ""
    file_size: int = 0
    width: int = 0
    height: int = 0
    downloaded_at: str = ""
    status: str = ""
    error: str = ""


def slugify(text: str, fallback: str = "item") -> str:
    value = re.sub(r"[^a-z0-9]+", "_", text.lower().strip()).strip("_")
    return value or fallback


def _srcset_urls(value: str | None) -> list[str]:
    if not value:
        return []

    ranked: list[tuple[float, str]] = []
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        rank = 0.0
        if len(bits) > 1:
            descriptor = bits[1].lower()
            match = re.fullmatch(r"(\d+(?:\.\d+)?)w", descriptor)
            if match:
                rank = float(match.group(1))
            else:
                match = re.fullmatch(r"(\d+(?:\.\d+)?)x", descriptor)
                if match:
                    rank = float(match.group(1)) * 1000
        ranked.append((rank, url))
    ranked.sort(reverse=True)
    return [url for _, url in ranked]


def _css_urls(style: str | None) -> list[str]:
    if not style:
        return []
    return [
        match.strip(" \t\r\n\"'")
        for match in re.findall(r"url\(([^)]+)\)", style, flags=re.IGNORECASE)
        if match.strip(" \t\r\n\"'")
    ]


def _tag_context(tag: Tag) -> str:
    chunks: list[str] = []
    for key in ("id", "alt", "title", "aria-label"):
        value = tag.get(key)
        if value:
            chunks.append(str(value))
    classes = tag.get("class") or []
    chunks.extend(str(value) for value in classes)

    parent = tag.parent if isinstance(tag.parent, Tag) else None
    if parent is not None:
        if parent.get("id"):
            chunks.append(str(parent.get("id")))
        chunks.extend(str(value) for value in (parent.get("class") or []))

    return " ".join(chunks).lower()


def _name_tokens(item_name: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", item_name.lower()) if len(token) >= 3]


def _score_candidate(
    url: str,
    *,
    item_id: int,
    item_name: str,
    context: str,
    source: str,
    width: int = 0,
    height: int = 0,
) -> int:
    decoded_url = unquote(url).lower()
    combined = f"{decoded_url} {context.lower()}"
    score = 0

    if str(item_id) in decoded_url:
        score += 25

    for token in _name_tokens(item_name):
        if token in decoded_url:
            score += 8
        if token in context.lower():
            score += 6

    for word in POSITIVE_WORDS:
        if word in combined:
            score += 3

    for word in REJECT_WORDS:
        if word in combined:
            score -= 80

    if source == "anchor_fullsize":
        score += 12
    elif source in {"og:image", "twitter:image", "jsonld"}:
        score += 8
    elif source == "img":
        score += 5
    elif source == "background":
        score += 2

    if width >= 128:
        score += 2
    if height >= 128:
        score += 2
    if width >= 300 and height >= 300:
        score += 3

    path = urlparse(url).path.lower()
    suffix = Path(path).suffix
    if suffix in IMAGE_EXTENSIONS:
        score += 2

    return score


def extract_image_candidates(
    html: str,
    page_url: str,
    item_id: int,
    item_name: str,
) -> list[ImageCandidate]:
    """Return ranked image candidates from an item HTML page.

    Coryn's item images are HTML-only metadata, so this deliberately supports
    several common patterns: normal/lazy <img>, srcset, linked full-size images,
    OpenGraph/Twitter metadata, JSON-LD, and CSS background-image URLs.
    """

    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, ImageCandidate] = {}

    def add(raw_url: str | None, source: str, context: str = "", width: int = 0, height: int = 0) -> None:
        if not raw_url:
            return
        raw_url = str(raw_url).strip()
        if not raw_url or raw_url.startswith(("data:", "javascript:", "#")):
            return
        url = urljoin(page_url, raw_url)
        if urlparse(url).scheme not in {"http", "https"}:
            return

        score = _score_candidate(
            url,
            item_id=item_id,
            item_name=item_name,
            context=context,
            source=source,
            width=width,
            height=height,
        )
        current = candidates.get(url)
        candidate = ImageCandidate(url=url, score=score, source=source, context=context)
        if current is None or candidate.score > current.score:
            candidates[url] = candidate

    # OpenGraph / Twitter / generic metadata.
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        content = meta.get("content")
        if not content:
            continue
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src", "image"}:
            add(content, "og:image" if key.startswith("og:") else "twitter:image", key)

    # JSON-LD can contain image as a string or list.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text("", strip=True)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.lower() in {"image", "contenturl", "thumbnailurl"}:
                        if isinstance(child, str):
                            add(child, "jsonld", key)
                        elif isinstance(child, list):
                            for item in child:
                                if isinstance(item, str):
                                    add(item, "jsonld", key)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)

    # Normal and lazy-loaded images, preferring a linked full-size original.
    for img in soup.find_all("img"):
        context = _tag_context(img)
        try:
            width = int(re.sub(r"\D", "", str(img.get("width") or "0")) or 0)
            height = int(re.sub(r"\D", "", str(img.get("height") or "0")) or 0)
        except ValueError:
            width = height = 0

        image_urls: list[str] = []
        for attr in ("data-full", "data-original", "data-src", "data-lazy-src", "data-image", "src"):
            value = img.get(attr)
            if value:
                image_urls.append(str(value))
        image_urls.extend(_srcset_urls(img.get("srcset")))
        image_urls.extend(_srcset_urls(img.get("data-srcset")))

        for image_url in image_urls:
            add(image_url, "img", context, width, height)

        parent = img.find_parent("a")
        if isinstance(parent, Tag):
            href = parent.get("href")
            if href:
                href_text = str(href)
                path = urlparse(urljoin(page_url, href_text)).path.lower()
                target_blank = str(parent.get("target") or "").lower() == "_blank"
                has_item_context = any(word in context for word in POSITIVE_WORDS) or any(
                    token in context for token in _name_tokens(item_name)
                )
                # An image extension is a strong signal. A target=_blank link around an
                # item-looking image also matches Coryn's "opens full size in a new tab" behavior.
                if Path(path).suffix in IMAGE_EXTENSIONS or (target_blank and has_item_context):
                    add(href_text, "anchor_fullsize", context, width, height)

    # Some pages use a direct image anchor without an <img> child.
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href"))
        absolute = urljoin(page_url, href)
        suffix = Path(urlparse(absolute).path.lower()).suffix
        if suffix in IMAGE_EXTENSIONS:
            add(href, "anchor_fullsize", _tag_context(anchor))

    # CSS backgrounds / custom data attributes.
    for tag in soup.find_all(True):
        context = _tag_context(tag)
        for css_url in _css_urls(tag.get("style")):
            add(css_url, "background", context)
        for attr, value in tag.attrs.items():
            if not isinstance(value, str):
                continue
            attr_lower = attr.lower()
            if any(word in attr_lower for word in ("image", "photo", "thumbnail", "preview")):
                add(value, "data_attribute", context)

    return sorted(candidates.values(), key=lambda c: (-c.score, c.url))


def looks_like_image_response(content_type: str, content: bytes, image_url: str) -> bool:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return True

    # Some servers return application/octet-stream or no Content-Type for static files.
    signatures = (
        b"\xff\xd8\xff",              # JPEG
        b"\x89PNG\r\n\x1a\n",      # PNG
        b"GIF87a",
        b"GIF89a",
        b"RIFF",                           # WebP is RIFF....WEBP (checked below)
        b"BM",                             # BMP
    )
    if content.startswith(signatures[:4]) or content.startswith(b"BM"):
        return True
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return True

    suffix = Path(urlparse(image_url).path).suffix.lower()
    return suffix in IMAGE_EXTENSIONS and bool(content)


def extension_for_image(content_type: str, image_url: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[normalized]

    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".img"


class ItemImageCrawler:
    def __init__(self, settings: Settings, client: CorynHttpClient, root: Path):
        self.settings = settings
        self.client = client
        self.root = root
        self.image_dir = root / "images" / "items"
        self.detail_dir = root / "raw" / "image_details" / "items"
        self.raw_index = root / "raw" / "item_images.jsonl"
        self.csv_index = root / "processed" / "item_images.csv"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.detail_dir.mkdir(parents=True, exist_ok=True)

    def _result_from_cache(self, path: Path) -> ItemImageResult | None:
        cached = load_json(path)
        if not isinstance(cached, dict):
            return None
        try:
            result = ItemImageResult(**cached)
        except TypeError:
            return None

        if result.status == "downloaded":
            local = self.root / result.local_path if result.local_path else None
            if local is None or not local.exists():
                return None
            # Backfill metadata when resuming caches created by older crawler versions.
            if not result.sha256 or not result.file_size:
                content = local.read_bytes()
                result.sha256 = hashlib.sha256(content).hexdigest()
                result.file_size = len(content)
                if not result.width or not result.height:
                    try:
                        with Image.open(io.BytesIO(content)) as image:
                            result.width, result.height = image.size
                    except Exception:
                        pass
                if not result.downloaded_at:
                    result.downloaded_at = datetime.fromtimestamp(
                        local.stat().st_mtime, tz=timezone.utc
                    ).isoformat()
                self._save_result(result)
            return result
        if result.status == "no_image":
            return result
        # Errors are retried on the next run.
        return None

    def _save_result(self, result: ItemImageResult) -> None:
        save_json(self.detail_dir / f"{result.item_id}.json", asdict(result))

    def _write_indexes(self) -> list[ItemImageResult]:
        results: list[ItemImageResult] = []
        def sort_key(path: Path) -> tuple[int, int | str]:
            return (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem)

        for path in sorted(self.detail_dir.glob("*.json"), key=sort_key):
            payload = load_json(path)
            if not isinstance(payload, dict):
                continue
            try:
                results.append(ItemImageResult(**payload))
            except TypeError:
                log.warning("Skipping malformed image result %s", path)

        rows = [asdict(result) for result in results]
        save_jsonl(self.raw_index, rows)
        save_csv(
            self.csv_index,
            rows,
            [
                "item_id",
                "item_name",
                "page_url",
                "image_url",
                "local_path",
                "content_type",
                "sha256",
                "file_size",
                "width",
                "height",
                "downloaded_at",
                "status",
                "error",
            ],
        )
        return results

    def crawl(
        self,
        items: list[dict[str, Any]],
        *,
        resume: bool = True,
        limit: int | None = None,
    ) -> list[ItemImageResult]:
        selected = items[:limit] if limit is not None else items
        total = len(selected)

        for index, item in enumerate(selected, start=1):
            raw_id = item.get("id", item.get("item_id"))
            name = str(item.get("name") or item.get("item_name") or "").strip()
            if raw_id is None or not name:
                log.warning("Skipping item without id/name: %r", item)
                continue

            item_id = int(raw_id)
            page_url = f"{self.settings.site_url}/item.php?id={item_id}"
            result_path = self.detail_dir / f"{item_id}.json"

            if resume and result_path.exists():
                cached = self._result_from_cache(result_path)
                if cached is not None:
                    if index == 1 or index % 100 == 0 or index == total:
                        log.info("item images: %s/%s (cached)", index, total)
                    continue

            try:
                html = self.client.get_text_url(page_url)
                candidates = extract_image_candidates(html, page_url, item_id, name)

                chosen: ImageCandidate | None = None
                image_bytes = b""
                content_type = ""
                candidate_errors: list[str] = []

                # Try strong candidates first. The response's Content-Type is the final validator.
                for candidate in candidates:
                    if candidate.score < -20:
                        continue
                    try:
                        binary = self.client.get_bytes_url(candidate.url)
                    except Exception as exc:  # noqa: BLE001 - save per-item crawl failures instead of aborting the run
                        candidate_errors.append(f"{candidate.url}: {type(exc).__name__}: {exc}")
                        continue
                    if not looks_like_image_response(binary.content_type, binary.content, binary.url):
                        candidate_errors.append(f"{candidate.url}: response did not look like an image ({binary.content_type!r})")
                        continue
                    chosen = candidate
                    image_bytes = binary.content
                    content_type = binary.content_type
                    break

                if chosen is None:
                    result = ItemImageResult(
                        item_id=item_id,
                        item_name=name,
                        page_url=page_url,
                        status="no_image",
                        error=" | ".join(candidate_errors[:3]),
                    )
                else:
                    extension = extension_for_image(content_type, chosen.url)
                    filename = f"{item_id}_{slugify(name, str(item_id))}{extension}"
                    path = self.image_dir / filename
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_bytes(image_bytes)
                    tmp.replace(path)
                    local_path = path.relative_to(self.root).as_posix()
                    width = 0
                    height = 0
                    try:
                        with Image.open(io.BytesIO(image_bytes)) as image:
                            width, height = image.size
                    except Exception:  # Some test/legacy images may have valid signatures but incomplete metadata.
                        pass
                    result = ItemImageResult(
                        item_id=item_id,
                        item_name=name,
                        page_url=page_url,
                        image_url=chosen.url,
                        local_path=local_path,
                        content_type=content_type,
                        sha256=hashlib.sha256(image_bytes).hexdigest(),
                        file_size=len(image_bytes),
                        width=width,
                        height=height,
                        downloaded_at=datetime.now(timezone.utc).isoformat(),
                        status="downloaded",
                    )

            except Exception as exc:  # noqa: BLE001 - one broken item must not terminate thousands of downloads
                log.exception("Image crawl failed for item %s (%s)", item_id, name)
                result = ItemImageResult(
                    item_id=item_id,
                    item_name=name,
                    page_url=page_url,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                )

            self._save_result(result)
            if index == 1 or index % 25 == 0 or index == total:
                log.info("item images: %s/%s status=%s", index, total, result.status)

        return self._write_indexes()
