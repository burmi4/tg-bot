"""Scraper for icetrade.by — Belarusian electronic trading platform."""

from __future__ import annotations

import logging
from urllib.parse import quote, urlencode

from crawlee.crawlers import PlaywrightCrawlingContext
from playwright.async_api import ElementHandle, Page

from tender_bot.models import TenderItem
from tender_bot.scrapers.base import create_stealth_crawler

logger = logging.getLogger(__name__)

_BASE_URL = "https://icetrade.by/search/auctions"


def _build_search_url(keyword: str) -> str:
    """Build an icetrade.by search URL for a keyword."""
    params = {
        "search_text": keyword,
        "search": "Найти",
        "zakup_type[1]": "1",
        "zakup_type[2]": "1",
        "auc_num": "",
        "okrb": "",
        "company_title": "",
        "establishment": "0",
        "period": "",
        "created_from": "",
        "created_to": "",
        "request_end_from": "",
        "request_end_to": "",
        "t[Trade]": "1",
        "t[eTrade]": "1",
        "t[Request]": "1",
        "t[singleSource]": "1",
        "t[Auction]": "1",
        "t[Other]": "1",
        "t[contractingTrades]": "1",
        "t[socialOrder]": "1",
        "t[negotiations]": "1",
        "r[1]": "1",
        "r[2]": "2",
        "r[7]": "7",
        "r[3]": "3",
        "r[4]": "4",
        "r[6]": "6",
        "r[5]": "5",
        "sort": "num:desc",
        "onPage": "20",
    }
    return f"{_BASE_URL}?{urlencode(params, quote_via=quote)}"


async def scrape_icetrade(keywords: list[str]) -> list[TenderItem]:
    """Scrape icetrade.by for auctions matching any of the given keywords.

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
    logger.info("icetrade.by: found %d unique tenders for keywords %s", len(result), keywords)
    return result


async def _scrape_single_keyword(url: str, keyword: str) -> list[TenderItem]:
    """Scrape a single search results page from icetrade.by."""
    tenders: list[TenderItem] = []
    crawler = create_stealth_crawler(max_requests=1)

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        await page.wait_for_load_state("networkidle", timeout=15000)

        # icetrade.by shows results in a table or as a list of links
        # Each tender is a link to /tenders/all/view/XXXXXX
        rows = await page.query_selector_all("table.auctions-table tbody tr")

        if rows:
            await _parse_table_rows(rows, tenders)
        else:
            # Fallback: parse links directly from the page content
            await _parse_link_list(page, tenders)

        context.log.info(
            "icetrade.by [%s]: parsed %d tenders", keyword, len(tenders)
        )

    try:
        await crawler.run([url])
    except Exception:
        logger.exception("Failed to crawl icetrade.by for keyword '%s'", keyword)

    # Enrich with detail page data
    if tenders:
        await _enrich_tenders_from_details(tenders)

    return tenders


async def _parse_table_rows(
    rows: list[ElementHandle],
    tenders: list[TenderItem],
) -> None:
    """Parse tender data from table rows."""
    for row in rows:
        try:
            link_el = await row.query_selector("a[href*='/tenders/all/view/']")
            if link_el is None:
                continue

            title = (await link_el.inner_text()).strip()
            href = await link_el.get_attribute("href") or ""

            if not title or not href:
                continue

            if href.startswith("/"):
                href = f"https://icetrade.by{href}"

            tender_id = href.rstrip("/").split("/")[-1]

            cells = await row.query_selector_all("td")
            organization = ""
            deadline = ""

            if len(cells) >= 3:
                organization = (await cells[2].inner_text()).strip()
            if len(cells) >= 5:
                deadline = (await cells[4].inner_text()).strip()

            tenders.append(
                TenderItem(
                    source="icetrade",
                    tender_id=tender_id,
                    title=title,
                    url=href,
                    organization=organization,
                    deadline=deadline,
                )
            )
        except Exception:
            logger.exception("Error parsing icetrade table row")
            continue


async def _parse_link_list(
    page: Page,
    tenders: list[TenderItem],
) -> None:
    """Fallback parser: extract tender links directly from the page."""
    links = await page.query_selector_all("a[href*='/tenders/all/view/']")

    for link in links:
        try:
            title = (await link.inner_text()).strip()
            href = await link.get_attribute("href") or ""

            if not title or not href:
                continue

            if href.startswith("/"):
                href = f"https://icetrade.by{href}"

            tender_id = href.rstrip("/").split("/")[-1]

            # Try to get the parent row/container for extra details
            parent = await link.evaluate_handle("el => el.closest('tr') || el.parentElement")
            organization = ""
            if parent:
                full_text: str = await parent.evaluate("el => el.textContent || ''")
                parts = [p.strip() for p in full_text.split("\n") if p.strip()]
                if len(parts) >= 2:
                    for part in parts:
                        if part != title and len(part) > 5:
                            organization = part
                            break

            tenders.append(
                TenderItem(
                    source="icetrade",
                    tender_id=tender_id,
                    title=title,
                    url=href,
                    organization=organization,
                )
            )
        except Exception:
            logger.exception("Error parsing icetrade link")
            continue


async def _enrich_tenders_from_details(tenders: list[TenderItem]) -> None:
    """Visit each tender's detail page to extract max_price, published_at, work_period."""
    detail_crawler = create_stealth_crawler(max_requests=len(tenders) + 1)
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

        # icetrade.by detail page structure:
        # - Table #main-info has main fields (org, dates, prices)
        # - Table #lots-info has lot-specific fields (delivery period)
        # We scan all rows for label-value pairs.
        rows = await page.query_selector_all("table tr")
        for row in rows:
            cells = await row.query_selector_all("td, th")
            if len(cells) < 2:
                continue
            label = (await cells[0].inner_text()).strip().lower()
            value = (await cells[1].inner_text()).strip()
            if not value:
                continue

            if "ориентировочная стоимость" in label or "предельная стоимость" in label:
                tender.max_price = value
            elif "дата размещения" in label and not tender.published_at:
                tender.published_at = value
            elif "окончания приема" in label and not tender.deadline:
                tender.deadline = value
            elif (
                not tender.work_period
                and any(
                    kw in label
                    for kw in (
                        "срок поставки", "срок выполнения",
                        "срок производства", "срок оказания",
                    )
                )
            ):
                tender.work_period = value

    try:
        await detail_crawler.run(detail_urls)
    except Exception:
        logger.exception("Failed to enrich icetrade tenders from detail pages")
