"""Periodic scheduler that orchestrates tender scraping and Telegram notifications."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from tender_bot.config import settings
from tender_bot.db import get_all_subscribers, is_tender_seen, mark_tender_seen
from tender_bot.models import TenderItem
from tender_bot.scrapers.goszakupki import scrape_goszakupki
from tender_bot.scrapers.icetrade import scrape_icetrade

logger = logging.getLogger(__name__)

# Track last poll stats for /status command
last_poll_stats: dict[str, object] = {
    "last_run": None,
    "tenders_found": 0,
    "tenders_sent": 0,
    "errors": 0,
}


def _get_error_count() -> int:
    """Get the current error count from stats."""
    val = last_poll_stats.get("errors", 0)
    if val is None:
        return 0
    return int(str(val))


def _format_tender_message(tender: TenderItem) -> str:
    """Format a tender item as a Telegram-friendly message."""
    source_label = (
        "goszakupki.by" if tender.source == "goszakupki" else "icetrade.by"
    )
    lines = [f"🔔 <b>Новый тендер</b> ({source_label})\n"]
    lines.append(f"📋 <b>{tender.title}</b>")

    if tender.organization:
        lines.append(f"🏢 {tender.organization}")

    # Max price / limit price
    if tender.max_price:
        lines.append(f"💰 Предельная стоимость: {tender.max_price}")
    elif tender.price:
        lines.append(f"💰 Стоимость: {tender.price}")
    else:
        lines.append("💰 Предельная стоимость: Не указана")

    # Publication date
    if tender.published_at:
        lines.append(f"📅 Размещён: {tender.published_at}")

    # Application deadline
    if tender.deadline:
        lines.append(f"⏰ Подача до: {tender.deadline}")

    # Work execution period
    if tender.work_period:
        lines.append(f"🔧 Срок работ: {tender.work_period}")

    if tender.status:
        lines.append(f"📊 Статус: {tender.status}")
    if tender.tender_type:
        lines.append(f"📝 Тип: {tender.tender_type}")

    lines.append(f'\n🔗 <a href="{tender.url}">Открыть тендер</a>')
    return "\n".join(lines)


def _is_blocked(tender: TenderItem, block_words: list[str]) -> bool:
    """Return True if the tender title contains any block word (case-insensitive)."""
    title_lower = tender.title.lower()
    return any(bw.lower() in title_lower for bw in block_words)


async def _poll_tenders(bot: Bot) -> None:
    """Run one polling cycle: scrape both sites, filter, notify."""
    logger.info("Starting tender poll cycle...")
    last_poll_stats["last_run"] = datetime.now().isoformat()
    last_poll_stats["errors"] = 0

    subscribers = await get_all_subscribers()
    if not subscribers:
        logger.info("No active subscribers, skipping poll.")
        return

    # Collect unique keywords across all subscribers
    all_keywords: set[str] = set()
    for sub in subscribers:
        kw_list: list[str] = sub["keywords"]  # type: ignore[assignment]
        all_keywords.update(kw_list)

    keyword_list = list(all_keywords)
    logger.info("Polling with keywords: %s", keyword_list)

    # Scrape both sites in parallel
    goszakupki_tenders: list[TenderItem] = []
    icetrade_tenders: list[TenderItem] = []

    try:
        goszakupki_tenders, icetrade_tenders = await asyncio.gather(
            scrape_goszakupki(keyword_list),
            scrape_icetrade(keyword_list),
        )
    except Exception:
        logger.exception("Error during parallel scraping")
        last_poll_stats["errors"] = _get_error_count() + 1

    all_tenders = goszakupki_tenders + icetrade_tenders
    last_poll_stats["tenders_found"] = len(all_tenders)

    # Filter out already seen tenders and notify subscribers
    new_tenders: list[TenderItem] = []
    for tender in all_tenders:
        if not await is_tender_seen(tender.source, tender.tender_id):
            new_tenders.append(tender)
            await mark_tender_seen(tender)

    last_poll_stats["tenders_sent"] = len(new_tenders)

    if not new_tenders:
        logger.info("No new tenders found this cycle.")
        return

    logger.info("Sending %d new tenders to %d subscribers", len(new_tenders), len(subscribers))

    for tender in new_tenders:
        message = _format_tender_message(tender)
        for sub in subscribers:
            chat_id: int = sub["chat_id"]  # type: ignore[assignment]
            # Check if the tender matches this user's keywords
            user_kw: list[str] = sub["keywords"]  # type: ignore[assignment]
            user_bw: list[str] = sub.get("block_words", [])  # type: ignore[assignment]

            title_lower = tender.title.lower()
            if not any(kw.lower() in title_lower for kw in user_kw):
                continue

            # Skip tenders matching block words
            if _is_blocked(tender, user_bw):
                logger.debug(
                    "Tender '%s' blocked for chat %d by block words",
                    tender.tender_id,
                    chat_id,
                )
                continue

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("Failed to send tender to chat %d", chat_id)
                last_poll_stats["errors"] = _get_error_count() + 1

            # Small delay to avoid Telegram rate limits
            await asyncio.sleep(0.1)


def start_scheduler(bot: Bot) -> Any:
    """Create and start the APScheduler for periodic tender polling."""
    scheduler: Any = AsyncIOScheduler()
    scheduler.add_job(
        _poll_tenders,
        "interval",
        seconds=settings.poll_interval_seconds,
        args=[bot],
        id="tender_poll",
        name="Poll tenders from goszakupki.by and icetrade.by",
        max_instances=1,  # Prevent overlapping runs
    )
    scheduler.start()
    logger.info(
        "Scheduler started: polling every %d seconds", settings.poll_interval_seconds
    )
    return scheduler
