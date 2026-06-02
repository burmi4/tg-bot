"""CloakBrowser integration for stealth Playwright crawling."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from cloakbrowser.config import (  # type: ignore[import-untyped]
    IGNORE_DEFAULT_ARGS,
    get_default_stealth_args,
)
from cloakbrowser.download import ensure_binary  # type: ignore[import-untyped]
from crawlee.crawlers import PlaywrightCrawler

logger = logging.getLogger(__name__)

# Download / locate the CloakBrowser Chromium binary once at import time.
_CLOAK_BINARY: str = ensure_binary()  # type: ignore[no-untyped-call]

# Crawlee persists its request queue to disk by default.  If the same URL
# has been crawled once it is marked "handled" (state 6) and will be
# skipped on every subsequent crawler run — even across process restarts.
# We purge the storage directory before every crawl to force fresh fetches.
_STORAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "storage"


def _purge_crawlee_storage() -> None:
    """Delete Crawlee's on-disk request queue so URLs are re-fetched."""
    rq_dir = _STORAGE_DIR / "request_queues"
    if rq_dir.exists():
        shutil.rmtree(rq_dir, ignore_errors=True)
        logger.debug("Purged Crawlee request queue storage at %s", rq_dir)


def create_stealth_crawler(max_requests: int = 1) -> PlaywrightCrawler:
    """Create a PlaywrightCrawler with CloakBrowser stealth settings.

    CloakBrowser modifies fingerprints at the C++ level, so we disable
    Crawlee's default JS-based fingerprinting to avoid conflicts.

    The request-queue storage is purged before each crawler instance to
    prevent the "only first run finds results" bug.
    """
    _purge_crawlee_storage()

    stealth_args: list[str] = get_default_stealth_args()  # type: ignore[no-untyped-call]
    launch_options: dict[str, Any] = {
        "executable_path": _CLOAK_BINARY,
        "ignore_default_args": IGNORE_DEFAULT_ARGS,
        "args": stealth_args,
        "headless": True,
    }

    crawler_kwargs: dict[str, Any] = {
        "max_requests_per_crawl": max_requests,
        "headless": True,
        "browser_launch_options": launch_options,
    }

    crawler = PlaywrightCrawler(**crawler_kwargs)
    logger.info("Created stealth crawler with CloakBrowser binary: %s", _CLOAK_BINARY)
    return crawler
