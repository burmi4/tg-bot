"""SQLite database layer for tracking seen tenders and user settings."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import aiosqlite

from tender_bot.config import settings

if TYPE_CHECKING:
    from tender_bot.models import TenderItem

logger = logging.getLogger(__name__)

_DB_PATH = settings.db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    tender_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    organization TEXT DEFAULT '',
    price TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    status TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    found_at TEXT NOT NULL,
    UNIQUE(source, tender_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    chat_id INTEGER PRIMARY KEY,
    keywords TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1
);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("Database initialized at %s", _DB_PATH)


async def is_tender_seen(source: str, tender_id: str) -> bool:
    """Check whether we have already sent this tender."""
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM seen_tenders WHERE source = ? AND tender_id = ?",
            (source, tender_id),
        )
        row = await cursor.fetchone()
        return row is not None


async def mark_tender_seen(tender: TenderItem) -> None:
    """Persist a tender so it won't be sent again."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO seen_tenders
               (source, tender_id, title, url, organization, price,
                deadline, status, tender_type, found_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tender.source,
                tender.tender_id,
                tender.title,
                tender.url,
                tender.organization,
                tender.price,
                tender.deadline,
                tender.status,
                tender.tender_type,
                tender.found_at.isoformat(),
            ),
        )
        await db.commit()


async def get_user_keywords(chat_id: int) -> list[str]:
    """Return the keyword list for a given user."""
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT keywords FROM user_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return list(settings.default_keywords)
        raw: str = row[0]
        result: list[str] = json.loads(raw)
        return result


async def set_user_keywords(chat_id: int, keywords: list[str]) -> None:
    """Create or update keyword list for a user."""
    kw_json = json.dumps(keywords, ensure_ascii=False)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_settings (chat_id, keywords, enabled)
               VALUES (?, ?, 1)
               ON CONFLICT(chat_id) DO UPDATE SET keywords = excluded.keywords""",
            (chat_id, kw_json),
        )
        await db.commit()


async def register_user(chat_id: int) -> None:
    """Register a new subscriber with default keywords."""
    kw_json = json.dumps(settings.default_keywords, ensure_ascii=False)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO user_settings (chat_id, keywords, enabled)
               VALUES (?, ?, 1)""",
            (chat_id, kw_json),
        )
        await db.commit()


async def set_user_enabled(chat_id: int, enabled: bool) -> None:
    """Enable or disable notifications for a user."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE user_settings SET enabled = ? WHERE chat_id = ?",
            (1 if enabled else 0, chat_id),
        )
        await db.commit()


async def get_all_subscribers() -> list[dict[str, object]]:
    """Return all active subscribers with their keywords."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chat_id, keywords, enabled FROM user_settings WHERE enabled = 1"
        )
        rows = await cursor.fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            keywords_raw: str = row["keywords"]  # type: ignore[index]
            keywords_list: list[str] = json.loads(keywords_raw)
            result.append({
                "chat_id": int(row["chat_id"]),  # type: ignore[index]
                "keywords": keywords_list,
            })
        return result
