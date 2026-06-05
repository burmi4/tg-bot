"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """Load .env file from project root."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)


_load_env()


@dataclass(frozen=True, slots=True)
class Settings:
    """Bot configuration settings."""

    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    default_chat_id: str = field(default_factory=lambda: os.getenv("DEFAULT_CHAT_ID", ""))
    default_keywords: list[str] = field(
        default_factory=lambda: [
            kw.strip()
            for kw in os.getenv(
                "DEFAULT_KEYWORDS", "Геодез,Изыск,Вынос,Разбив,Исполнительная"
            ).split(",")
            if kw.strip()
        ]
    )
    stop_words: list[str] = field(
        default_factory=lambda: [
            kw.strip()
            for kw in os.getenv(
                "STOP_WORDS",
                "детального обследования,"
                "Разработка предпроектной и проектной,"
                "предпроектной (предынвестиционной",
            ).split(",")
            if kw.strip()
        ]
    )
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
    )
    db_path: str = field(
        default_factory=lambda: os.getenv(
            "DB_PATH",
            str(Path(__file__).resolve().parent.parent.parent / "tender_bot.db"),
        )
    )
    telegram_proxy: str = field(default_factory=lambda: os.getenv("TELEGRAM_PROXY", ""))

    def validate(self) -> None:
        """Raise ValueError if critical settings are missing."""
        if not self.bot_token:
            msg = "BOT_TOKEN is required. Set it in .env file."
            raise ValueError(msg)


settings = Settings()
