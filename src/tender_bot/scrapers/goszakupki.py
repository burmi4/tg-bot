"""Scraper for goszakupki.by — Belarusian government procurement portal."""

from __future__ import annotations

import logging
from urllib.parse import quote, urlencode

from crawlee.crawlers import PlaywrightCrawlingContext

from tender_bot.models import TenderItem
from tender_bot.scrapers.base import create_stealth_crawler

logger = logging.getLogger(__name__)

_BASE_URL = "https://goszakupki.by/tenders/posted"


def _build_search_url(keyword: str) -> str:
    """Build a goszakupki.by search URL for a keyword."""
    params = {
        "TendersSearch[text]": keyword,
        "TendersSearch[num]": "",
        "TendersSearch[iceGiasNum]": "",
        "TendersSearch[unp]": "",
        "TendersSearch[customer_text]": "",
        "TendersSearch[unpParticipant]": "",
        "TendersSearch[participant_text]": "",
        "TendersSearch[price_from]": "",
        "TendersSearch[price_to]": "",
        "TendersSearch[created_from]": "",
        "TendersSearch[created_to]": "",
        "TendersSearch[request_end_from]": "",
        "TendersSearch[request_end_to]": "",
        "TendersSearch[auction_date_from]": "",
        "TendersSearch[auction_date_to]": "",
        "TendersSearch[industry]": "",
        "TendersSearch[type]": "",
        "TendersSearch[status]": "",
        "TendersSearch[region]": "",
        "TendersSearch[appeal]": "",
        "TendersSearch[funds]": "",
    }
    return f"{_BASE_URL}?{urlencode(params, quote_via=quote)}"


async def scrape_goszakupki(keywords: list[str]) -> list[TenderItem]:
    """Scrape goszakupki.by for tenders matching any of the given keywords.

    Each keyword triggers a separate page load; results are merged and
    deduplicated by tender_id.
    """
    all_tenders: dict[str, TenderItem] = {}

    for keyword in keywords:
        url = _build_search_url(keyword)
        tenders = await _scrape_single_keyword(url, keyword)
        for t in tenders:
            all_tenders[t.tender_id] = t

    result = list(all_tenders.values())
    logger.info("goszakupki.by: found %d unique tenders for keywords %s", len(result), keywords)
    return result


async def _scrape_single_keyword(url: str, keyword: str) -> list[TenderItem]:
    """Scrape a single search results page."""
    tenders: list[TenderItem] = []
    crawler = create_stealth_crawler(max_requests=1)

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        # Wait for the tender table to load
        await page.wait_for_load_state("networkidle", timeout=15000)

        # goszakupki.by renders tenders in a table; each row is a tender
        # The main content table has rows with tender data
        rows = await page.query_selector_all("table.table tbody tr")

        if not rows:
            # Try alternative selector — the site sometimes uses divs
            rows = await page.query_selector_all(".tender-item, .search-results-item")

        for row in rows:
            try:
                # Extract the link element
                link_el = await row.query_selector("a[href*='/tenders/view/']")
                if link_el is None:
                    link_el = await row.query_selector("a[href*='/marketing/view/']")
                if link_el is None:
                    # Try any link inside the row
                    link_el = await row.query_selector("a[href]")

                if link_el is None:
                    continue

                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href") or ""

                if not title or not href:
                    continue

                # Build full URL
                if href.startswith("/"):
                    href = f"https://goszakupki.by{href}"

                # Extract tender ID from URL
                tender_id = href.rstrip("/").split("/")[-1]

                # Extract other cells from the row
                cells = await row.query_selector_all("td")
                organization = ""
                price = ""
                deadline = ""
                status = ""
                tender_type = ""

                if len(cells) >= 2:
                    organization = (await cells[1].inner_text()).strip()
                if len(cells) >= 4:
                    tender_type = (await cells[3].inner_text()).strip()
                if len(cells) >= 5:
                    status = (await cells[4].inner_text()).strip()
                if len(cells) >= 6:
                    deadline = (await cells[5].inner_text()).strip()
                if len(cells) >= 7:
                    price = (await cells[6].inner_text()).strip()

                tenders.append(
                    TenderItem(
                        source="goszakupki",
                        tender_id=tender_id,
                        title=title,
                        url=href,
                        organization=organization,
                        price=price,
                        deadline=deadline,
                        status=status,
                        tender_type=tender_type,
                    )
                )
            except Exception:
                logger.exception("Error parsing goszakupki row")
                continue

        context.log.info(
            "goszakupki.by [%s]: parsed %d tenders", keyword, len(tenders)
        )

    try:
        await crawler.run([url])
    except Exception:
        logger.exception("Failed to crawl goszakupki.by for keyword '%s'", keyword)

    return tenders
