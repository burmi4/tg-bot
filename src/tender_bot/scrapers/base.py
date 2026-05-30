"""CloakBrowser integration for stealth Playwright crawling."""

from __future__ import annotations

import logging
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


def create_stealth_crawler(max_requests: int = 1) -> PlaywrightCrawler:
    """Create a PlaywrightCrawler with CloakBrowser stealth settings.

    CloakBrowser modifies fingerprints at the C++ level, so we disable
    Crawlee's default JS-based fingerprinting to avoid conflicts.
    """
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
