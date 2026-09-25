from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from .config import Settings

log = logging.getLogger(__name__)


class CorynHttpClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "application/json",
            }
        )

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.settings.base_url}/{endpoint.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.settings.timeout)

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 2 ** attempt)
                    log.warning("HTTP 429 for %s; sleeping %.1fs", response.url, wait)
                    time.sleep(wait)
                    continue

                if 500 <= response.status_code < 600:
                    raise requests.HTTPError(f"server error {response.status_code}", response=response)

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object from Coryn API")
                if payload.get("success") is False:
                    raise RuntimeError(f"Coryn API returned success=false: {payload}")

                self._polite_delay()
                return payload

            except (requests.RequestException, ValueError, RuntimeError) as exc:
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

    def _polite_delay(self) -> None:
        delay = self.settings.request_delay
        if delay > 0:
            time.sleep(delay + random.uniform(0, min(0.10, delay / 3)))
