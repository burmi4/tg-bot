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
    # We need extra requests for detail pages: 1 for list + N for details.
    # Set a generous limit; we'll stop early if needed.
    crawler = create_stealth_crawler(max_requests=50)

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        # Wait for the tender table to load
        await page.wait_for_load_state("networkidle", timeout=15000)

        # goszakupki.by uses a Yii2 GridView with id="tenders-grid".
        # The table inside has class "table table-striped table-bordered".
        grid = await page.query_selector("#tenders-grid")
        if grid is None:
            # Fallback: try any table
            grid = await page.query_selector("table.table")

        if grid is None:
            context.log.info("goszakupki.by [%s]: no results grid found", keyword)
            return

        rows = await grid.query_selector_all("tbody tr")

        for row in rows:
            try:
                # The link to the tender may use various URL patterns:
                # /tenders/view/ID, /single-source/view/ID, /marketing/view/ID
                link_el = await row.query_selector("a[href*='/view/']")
                if link_el is None:
                    continue

                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href") or ""

                if not title or not href:
                    continue

                # Build full URL
                if href.startswith("/"):
                    href = f"https://goszakupki.by{href}"

                # Extract tender ID from URL (last segment)
                tender_id = href.rstrip("/").split("/")[-1]

                # Extract cells — goszakupki.by table structure:
                # Cell 0: Tender number (auc0003421250)
                # Cell 1: Organization + tender title link
                # Cell 2: Procedure type
                # Cell 3: Status
                # Cell 4: Deadline (proposals/documents deadline)
                # Cell 5: Estimated/limit price
                cells = await row.query_selector_all("td")
                organization = ""
                price = ""
                deadline = ""
                status = ""
                tender_type = ""

                if len(cells) >= 2:
                    # Cell 1 contains org name + link; get org from first text
                    full_text = (await cells[1].inner_text()).strip()
                    # Organization is usually before the tender title
                    text_parts = [p.strip() for p in full_text.split("\n") if p.strip()]
                    if len(text_parts) >= 2:
                        organization = text_parts[0]
                if len(cells) >= 3:
                    tender_type = (await cells[2].inner_text()).strip()
                if len(cells) >= 4:
                    status = (await cells[3].inner_text()).strip()
                if len(cells) >= 5:
                    deadline = (await cells[4].inner_text()).strip()
                if len(cells) >= 6:
                    price = (await cells[5].inner_text()).strip()

                tenders.append(
                    TenderItem(
                        source="goszakupki",
                        tender_id=tender_id,
                        title=title,
                        url=href,
                        organization=organization,
                        price=price,
                        max_price=price,  # from list page, price IS the limit price
                        deadline=deadline,
                        status=status,
                        tender_type=tender_type,
                    )
                )
            except Exception:
                logger.exception("Error parsing goszakupki row")
                continue

        context.log.info(
            "goszakupki.by [%s]: parsed %d tenders from list", keyword, len(tenders)
        )

    try:
        await crawler.run([url])
    except Exception:
        logger.exception("Failed to crawl goszakupki.by for keyword '%s'", keyword)

    # Now enrich each tender with detail page data.
    # Use a separate crawler for detail pages to avoid queue conflicts.
    if tenders:
        await _enrich_tenders_from_details(tenders)

    return tenders


async def _enrich_tenders_from_details(tenders: list[TenderItem]) -> None:
    """Visit each tender's detail page to extract additional fields."""
    detail_crawler = create_stealth_crawler(max_requests=len(tenders) + 1)
    # Map URL → tender for updating after crawl
    url_to_tender: dict[str, TenderItem] = {t.url: t for t in tenders}
    detail_urls = list(url_to_tender.keys())

    @detail_crawler.router.default_handler
    async def detail_handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        current_url = page.url
        await page.wait_for_load_state("networkidle", timeout=15000)

        tender = url_to_tender.get(current_url)
        if tender is None:
            # Try matching by tender_id in URL
            for _t_url, t_obj in url_to_tender.items():
                if t_obj.tender_id in current_url:
                    tender = t_obj
                    break
        if tender is None:
            return

        # Scan all table rows for label-value pairs
        rows = await page.query_selector_all("table tr")
        for row in rows:
            cells = await row.query_selector_all("td, th")
            if len(cells) < 2:
                continue
            label = (await cells[0].inner_text()).strip().lower()
            value = (await cells[1].inner_text()).strip()
            if not value:
                continue

            if "предельная стоимость" in label or "ориентировочная стоимость" in label:
                tender.max_price = value
            elif "дата размещения" in label:
                tender.published_at = value
            elif any(
                kw in label
                for kw in ("срок поставки", "срок выполнения", "срок производства", "срок оказания")
            ):
                tender.work_period = value

    try:
        await detail_crawler.run(detail_urls)
    except Exception:
        logger.exception("Failed to enrich goszakupki tenders from detail pages")
