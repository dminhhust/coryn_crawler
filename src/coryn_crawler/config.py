from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_url: str
    page_size: int
    request_delay: float
    timeout: float
    max_retries: int
    user_agent: str
    output_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        page_size = min(max(int(os.getenv("CORYN_PAGE_SIZE", "100")), 1), 100)
        return cls(
            base_url=os.getenv("CORYN_BASE_URL", "https://coryn.club/api/v1").rstrip("/"),
            page_size=page_size,
            request_delay=max(float(os.getenv("CORYN_REQUEST_DELAY", "0.30")), 0.0),
            timeout=max(float(os.getenv("CORYN_TIMEOUT", "30")), 1.0),
            max_retries=max(int(os.getenv("CORYN_MAX_RETRIES", "5")), 1),
            user_agent=os.getenv(
                "CORYN_USER_AGENT",
                "CorynResearchCrawler/0.1 (educational data collection; public API)",
            ),
            output_dir=Path(os.getenv("CORYN_OUTPUT_DIR", "data")),
        )
