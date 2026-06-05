"""Scraper for goszakupki.by — Belarusian government procurement portal."""

from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlencode

from crawlee import Request
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
        "_t": str(time.time()),
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
    crawler = create_stealth_crawler()

    @crawler.router.default_handler  # pyright: ignore[reportUnknownMemberType]
    async def handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        try:
            await page.wait_for_selector(
                "table.table tbody tr, .tender-item, .search-results-item",
                timeout=15000,
            )
        except Exception:
            logger.debug("Timeout waiting for goszakupki results, continuing to parse.")

        rows = await page.query_selector_all("table.table tbody tr")
        if not rows:
            rows = await page.query_selector_all(".tender-item, .search-results-item")

        for row in rows:
            try:
                link_el = await row.query_selector("a[href*='/tenders/view/']")
                if link_el is None:
                    link_el = await row.query_selector("a[href*='/marketing/view/']")
                if link_el is None:
                    link_el = await row.query_selector("a[href]")

                if link_el is None:
                    continue

                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href") or ""

                if not title or not href:
                    continue

                if href.startswith("/"):
                    href = f"https://goszakupki.by{href}"

                tender_id = href.rstrip("/").split("/")[-1]

                cells = await row.query_selector_all("td")
                organization = ""
                price = "Не указана"
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
                    if not price:
                        price = "Не указана"

                await context.add_requests([
                    Request.from_url(
                        href,
                        label="DETAIL",
                        user_data={
                            "tender_id": tender_id,
                            "title": title,
                            "url": href,
                            "organization": organization,
                            "price": price,
                            "deadline": deadline,
                            "status": status,
                            "tender_type": tender_type,
                        }
                    )
                ])
            except Exception:
                logger.exception("Error parsing goszakupki row")

        context.log.info("goszakupki.by [%s]: queued detail pages", keyword)

    @crawler.router.handler("DETAIL")  # pyright: ignore[reportUnknownMemberType]
    async def detail_handler(context: PlaywrightCrawlingContext) -> None:  # pyright: ignore[reportUnusedFunction]
        page = context.page
        user_data = context.request.user_data

        max_cost = str(user_data.get("price", "Не указана"))
        publish_period = ""
        submission_deadline = str(user_data.get("deadline", ""))
        execution_period = ""

        try:
            trs = await page.query_selector_all("tr")
            for tr in trs:
                th = await tr.query_selector("th")
                td = await tr.query_selector("td")
                if th and td:
                    th_text = (await th.inner_text()).strip()
                    td_text = (await td.inner_text()).strip()

                    if "стоимость" in th_text.lower():
                        max_cost = td_text
                    elif "Дата размещения" in th_text:
                        publish_period = td_text
                    elif "окончания приема" in th_text.lower() or "срок подачи" in th_text.lower():
                        submission_deadline = td_text
                    elif (
                        "Срок поставки" in th_text or
                        "Срок выполнения" in th_text or
                        "Срок оказания" in th_text
                    ):
                        execution_period = td_text

            tenders.append(
                TenderItem(
                    source="goszakupki",
                    tender_id=str(user_data.get("tender_id", "")),
                    title=str(user_data.get("title", "")),
                    url=str(user_data.get("url", "")),
                    organization=str(user_data.get("organization", "")),
                    status=str(user_data.get("status", "")),
                    tender_type=str(user_data.get("tender_type", "")),
                    max_cost=max_cost,
                    publish_period=publish_period,
                    submission_deadline=submission_deadline,
                    execution_period=execution_period,
                )
            )
        except Exception:
            logger.exception("Error parsing goszakupki detail page %s", context.request.url)

    try:
        await crawler.run([url])
    except Exception:
        logger.exception("Failed to crawl goszakupki.by for keyword '%s'", keyword)

    return tenders
