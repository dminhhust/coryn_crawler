from pathlib import Path

from coryn_crawler.api import CorynCrawler
from coryn_crawler.config import Settings


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if "id" in (params or {}):
            return {"success": True, "data": {"id": params["id"], "name": f"row-{params['id']}"}, "meta": {"version": "v1"}}
        offset = params["offset"]
        if offset == 0:
            return {
                "success": True,
                "data": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
                "meta": {"total": 3, "limit": 2, "offset": 0},
            }
        return {
            "success": True,
            "data": [{"id": 3, "name": "c"}],
            "meta": {"total": 3, "limit": 2, "offset": 2},
        }


def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url="https://example.invalid/api/v1",
        page_size=2,
        request_delay=0,
        timeout=1,
        max_retries=1,
        user_agent="test",
        output_dir=tmp_path,
    )


def test_paginated_collection_and_resume(tmp_path):
    fake = FakeClient()
    crawler = CorynCrawler(settings(tmp_path), fake, tmp_path)
    rows = crawler.crawl_collection("items", resume=True)
    assert [r["id"] for r in rows] == [1, 2, 3]

    # Completed state should prevent repeat network calls.
    before = len(fake.calls)
    again = crawler.crawl_collection("items", resume=True)
    assert again == rows
    assert len(fake.calls) == before


def test_detail_cache(tmp_path):
    fake = FakeClient()
    crawler = CorynCrawler(settings(tmp_path), fake, tmp_path)
    rows = [{"id": 1}, {"id": 2}]
    details = crawler.crawl_details("items", rows, resume=True)
    assert len(details) == 2
    calls = len(fake.calls)
    details2 = crawler.crawl_details("items", rows, resume=True)
    assert details2 == details
    assert len(fake.calls) == calls
