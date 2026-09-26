from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinaryResponse:
    content: bytes
    content_type: str
    url: str


class CorynHttpClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "*/*",
    ) -> requests.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.settings.timeout,
                    headers={"Accept": accept},
                )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else min(60.0, 2**attempt)
                    except ValueError:
                        wait = min(60.0, 2**attempt)
                    log.warning("HTTP 429 for %s; sleeping %.1fs", response.url, wait)
                    time.sleep(wait)
                    continue

                if 500 <= response.status_code < 600:
                    raise requests.HTTPError(f"server error {response.status_code}", response=response)

                response.raise_for_status()
                self._polite_delay()
                return response

            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                wait = min(30.0, (2 ** (attempt - 1)) + random.random())
                log.warning(
                    "Request failed (%s/%s): %s; retrying in %.1fs",
                    attempt,
                    self.settings.max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        assert last_error is not None
        raise last_error

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.settings.base_url}/{endpoint.lstrip('/')}"
        response = self._request(url, params=params, accept="application/json")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"Expected JSON from {response.url}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object from Coryn API")
        if payload.get("success") is False:
            raise RuntimeError(f"Coryn API returned success=false: {payload}")
        return payload

    def get_text_url(self, url: str) -> str:
        response = self._request(
            url,
            accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        )
        # requests guesses encoding from headers; apparent_encoding is a useful fallback for old pages.
        if not response.encoding:
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def get_bytes_url(self, url: str) -> BinaryResponse:
        response = self._request(
            url,
            accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        )
        return BinaryResponse(
            content=response.content,
            content_type=(response.headers.get("Content-Type") or "").split(";", 1)[0].strip(),
            url=response.url,
        )

    def _polite_delay(self) -> None:
        delay = self.settings.request_delay
        if delay > 0:
            time.sleep(delay + random.uniform(0, min(0.10, delay / 3)))
