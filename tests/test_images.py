from coryn_crawler.images import extract_image_candidates, extension_for_image, slugify


def test_prefers_linked_full_size_item_image_over_logo():
    html = """
    <html><head><meta property="og:image" content="/images/logo%203.png"></head>
    <body>
      <img src="/images/logo%203.png" alt="Coryn Club logo" width="1000" height="1000">
      <div class="item-detail main-image">
        <a class="item-image-link" href="/uploads/items/8571_reindeer_antlers_full.webp">
          <img src="/uploads/items/thumb/8571.webp" alt="Reindeer Antlers" width="320" height="320">
        </a>
      </div>
    </body></html>
    """
    candidates = extract_image_candidates(
        html,
        "https://coryn.club/item.php?id=8571",
        8571,
        "Reindeer Antlers",
    )
    assert candidates
    assert candidates[0].url == "https://coryn.club/uploads/items/8571_reindeer_antlers_full.webp"
    assert "logo" not in candidates[0].url


def test_css_background_image_can_be_discovered():
    html = """
    <div id="item-preview" style="background-image:url('/media/items/42_magic_sword.png')"></div>
    """
    candidates = extract_image_candidates(
        html,
        "https://coryn.club/item.php?id=42",
        42,
        "Magic Sword",
    )
    assert candidates[0].url == "https://coryn.club/media/items/42_magic_sword.png"


def test_helpers():
    assert slugify("Reindeer Antlers") == "reindeer_antlers"
    assert extension_for_image("image/jpeg", "https://example.invalid/file") == ".jpg"
    assert extension_for_image("application/octet-stream", "https://example.invalid/a.webp") == ".webp"


def test_target_blank_parent_can_represent_full_size_url_without_extension():
    html = """
    <a target="_blank" class="item-image" href="/image/show?id=8571">
      <img src="/thumb?id=8571" alt="Reindeer Antlers">
    </a>
    """
    candidates = extract_image_candidates(
        html,
        "https://coryn.club/item.php?id=8571",
        8571,
        "Reindeer Antlers",
    )
    assert candidates[0].url == "https://coryn.club/image/show?id=8571"


def test_octet_stream_with_png_signature_counts_as_image():
    from coryn_crawler.images import looks_like_image_response

    assert looks_like_image_response(
        "application/octet-stream",
        b"\x89PNG\r\n\x1a\nrest",
        "https://example.invalid/file",
    )


def test_item_image_crawler_writes_image_and_resumes(tmp_path):
    from pathlib import Path

    from coryn_crawler.config import Settings
    from coryn_crawler.http import BinaryResponse
    from coryn_crawler.images import ItemImageCrawler

    class FakeClient:
        def __init__(self):
            self.text_calls = 0
            self.byte_calls = 0

        def get_text_url(self, url):
            self.text_calls += 1
            return '''
            <div class="item-detail main-image">
              <a target="_blank" href="/uploads/8571_reindeer_antlers.png">
                <img src="/thumb/8571.png" alt="Reindeer Antlers">
              </a>
            </div>
            '''

        def get_bytes_url(self, url):
            self.byte_calls += 1
            return BinaryResponse(
                content=b"\x89PNG\r\n\x1a\nrest",
                content_type="image/png",
                url=url,
            )

    settings = Settings(
        base_url="https://example.invalid/api/v1",
        page_size=100,
        request_delay=0,
        timeout=1,
        max_retries=1,
        user_agent="test",
        output_dir=tmp_path,
        site_url="https://coryn.club",
    )
    fake = FakeClient()
    crawler = ItemImageCrawler(settings, fake, tmp_path)
    results = crawler.crawl([{"id": 8571, "name": "Reindeer Antlers"}], resume=True)

    assert results[0].status == "downloaded"
    assert (tmp_path / results[0].local_path).exists()
    assert (tmp_path / "processed" / "item_images.csv").exists()
    assert results[0].sha256
    assert results[0].file_size == len(b"\x89PNG\r\n\x1a\nrest")
    assert results[0].downloaded_at
    assert fake.text_calls == 1

    crawler.crawl([{"id": 8571, "name": "Reindeer Antlers"}], resume=True)
    assert fake.text_calls == 1
