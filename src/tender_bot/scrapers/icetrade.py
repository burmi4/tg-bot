"""Scraper for icetrade.by — Belarusian electronic trading platform."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlencode

from crawlee import Request
from crawlee.crawlers import PlaywrightCrawlingContext

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
        "_t": str(time.time()),
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
    crawler = create_stealth_crawler()

    @crawler.router.default_handler  # pyright: ignore[reportUnknownMemberType]
    async def handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        try:
            await page.wait_for_selector(
                "table.auctions-table tbody tr, a[href*='/tenders/all/view/']",
                timeout=15000,
            )
        except Exception:
            logger.debug("Timeout waiting for icetrade results, continuing to parse.")

        rows = await page.query_selector_all("table.auctions-table tbody tr")
        if rows:
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
                    if len(cells) >= 3:
                        organization = (await cells[2].inner_text()).strip()

                    await context.add_requests([
                        Request.from_url(
                            href,
                            label="DETAIL",
                            user_data={
                                "tender_id": tender_id,
                                "title": title,
                                "url": href,
                                "organization": organization,
                            }
                        )
                    ])
                except Exception:
                    logger.exception("Error parsing icetrade table row")
        else:
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
                    parent = await link.evaluate_handle(
                        "el => el.closest('tr') || el.parentElement"
                    )
                    organization = ""
                    if parent:
                        full_text: str = await parent.evaluate("el => el.textContent || ''")
                        parts = [p.strip() for p in full_text.split("\n") if p.strip()]
                        if len(parts) >= 2:
                            for part in parts:
                                if part != title and len(part) > 5:
                                    organization = part
                                    break

                    await context.add_requests([
                        Request.from_url(
                            href,
                            label="DETAIL",
                            user_data={
                                "tender_id": tender_id,
                                "title": title,
                                "url": href,
                                "organization": organization,
                            }
                        )
                    ])
                except Exception:
                    logger.exception("Error parsing icetrade link")

        context.log.info("icetrade.by [%s]: queued detail pages", keyword)


    @crawler.router.handler("DETAIL")  # pyright: ignore[reportUnknownMemberType]
    async def detail_handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        user_data = context.request.user_data

        max_cost = "Не указана"
        publish_period = ""
        submission_deadline = ""
        execution_period = ""

        try:
            trs = await page.query_selector_all("tr")
            for tr in trs:
                th = await tr.query_selector("th")
                td = await tr.query_selector("td")
                if th and td:
                    th_text = (await th.inner_text()).strip()
                    td_text = (await td.inner_text()).strip()

                    if "Общая ориентировочная стоимость" in th_text:
                        max_cost = td_text
                    elif "Дата размещения" in th_text:
                        publish_period = td_text
                    elif "окончания приема предложений" in th_text:
                        submission_deadline = td_text
                    elif "Срок поставки" in th_text or "Срок производства" in th_text:
                        execution_period = td_text

            item = TenderItem(
                source="icetrade",
                tender_id=str(user_data.get("tender_id", "")),
                title=str(user_data.get("title", "")),
                url=str(user_data.get("url", "")),
                organization=str(user_data.get("organization", "")),
                max_cost=max_cost,
                publish_period=publish_period,
                submission_deadline=submission_deadline,
                execution_period=execution_period,
            )
            tenders.append(item)
        except Exception:
            logger.exception("Error parsing icetrade detail page %s", context.request.url)

    try:
        await crawler.run([url])
    except Exception:
        logger.exception("Failed to crawl icetrade.by for keyword '%s'", keyword)

    return tenders
