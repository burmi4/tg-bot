"""Entry point for the tender monitoring Telegram bot."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

from tender_bot.bot.handlers import router
from tender_bot.config import settings
from tender_bot.db import init_db
from tender_bot.scrapers.scheduler import start_scheduler


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)


def setup_logging() -> None:
    """Set up console and JSON file logging."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(console_handler)

    # File handler (JSONL)
    file_handler = RotatingFileHandler(
        log_dir / "bot.jsonl",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger.addHandler(file_handler)


setup_logging()
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
        await dp.start_polling(bot)  # pyright: ignore[reportUnknownMemberType]
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted by user.")
