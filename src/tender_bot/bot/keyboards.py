"""Inline keyboards for the Telegram bot UI."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def keywords_keyboard(keywords: list[str]) -> InlineKeyboardMarkup:
    """Build a keyboard showing current keywords with delete buttons."""
    buttons: list[list[InlineKeyboardButton]] = []
    for kw in keywords:
        buttons.append([
            InlineKeyboardButton(text=f"❌ {kw}", callback_data=f"rm_kw:{kw}"),
        ])
    buttons.append([
        InlineKeyboardButton(text="➕ Добавить слово", callback_data="add_kw"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Yes/No confirmation keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="cancel"),
        ]
    ])


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu with key actions."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Ключевые слова", callback_data="show_keywords")],
        [InlineKeyboardButton(text="📊 Статус", callback_data="show_status")],
        [InlineKeyboardButton(text="⏸ Пауза", callback_data="pause_notifications")],
        [InlineKeyboardButton(text="▶️ Возобновить", callback_data="resume_notifications")],
    ])
