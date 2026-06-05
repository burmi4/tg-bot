"""Entry point for the tender monitoring Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

from tender_bot.bot.handlers import router
from tender_bot.config import settings
from tender_bot.db import init_db
from tender_bot.scrapers.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize and run the bot with the scraping scheduler."""
    # Validate configuration
    settings.validate()

    # Initialize database
    await init_db()

    # Configure proxy if provided
    session = AiohttpSession(proxy=settings.telegram_proxy) if settings.telegram_proxy else None

    # Create bot and dispatcher
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Start the periodic tender scraper
    scheduler = start_scheduler(bot)

    logger.info("Bot is starting... (poll interval: %ds)", settings.poll_interval_seconds)

    try:
        while True:
            try:
                await dp.start_polling(bot)  # pyright: ignore[reportUnknownMemberType]
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Polling error (network disconnect): %s. Retrying in 5 seconds...", e)
                await asyncio.sleep(5)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user.")
