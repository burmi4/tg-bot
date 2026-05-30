"""Telegram bot command and callback handlers."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from tender_bot.bot.keyboards import keywords_keyboard, main_menu_keyboard
from tender_bot.config import settings
from tender_bot.db import (
    get_user_keywords,
    register_user,
    set_user_enabled,
    set_user_keywords,
)
from tender_bot.scrapers.scheduler import last_poll_stats

logger = logging.getLogger(__name__)

router = Router(name="main")


# ── FSM States ───────────────────────────────────────────────────────────────


class AddKeywordState(StatesGroup):
    """FSM for waiting for a new keyword input."""

    waiting_for_keyword = State()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_callback_message(callback: CallbackQuery) -> Message | None:
    """Safely extract a regular Message from a callback, or None."""
    msg = callback.message
    if msg is None:
        return None
    # InaccessibleMessage has date == 0; regular Message has a real date.
    # We avoid isinstance per project rules and use attribute check instead.
    if not hasattr(msg, "edit_text"):
        return None
    return msg  # type: ignore[return-value]


def _get_poll_stat_str(key: str, default: str = "") -> str:
    """Safely get a string value from the poll stats dict."""
    val = last_poll_stats.get(key)
    if val is None:
        return default
    return str(val)


def _get_poll_stat_int(key: str, default: int = 0) -> int:
    """Safely get an int value from the poll stats dict."""
    val = last_poll_stats.get(key)
    if val is None:
        return default
    return int(str(val))


# ── /start ───────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Register user and show welcome message."""
    if message.from_user is None:
        return

    chat_id = message.chat.id
    await register_user(chat_id)
    keywords = await get_user_keywords(chat_id)

    welcome = (
        "👋 <b>Добро пожаловать в бот мониторинга тендеров!</b>\n\n"
        "Я автоматически отслеживаю новые тендеры на:\n"
        "• <b>goszakupki.by</b>\n"
        "• <b>icetrade.by</b>\n\n"
        f"🔑 <b>Ключевые слова для поиска:</b>\n"
        f"{', '.join(keywords)}\n\n"
        f"⏱ Интервал проверки: каждые {settings.poll_interval_seconds} сек.\n\n"
        "Используйте меню ниже для настройки:"
    )
    await message.answer(
        welcome, parse_mode="HTML", reply_markup=main_menu_keyboard()
    )


# ── /keywords ────────────────────────────────────────────────────────────────


@router.message(Command("keywords"))
async def cmd_keywords(message: Message) -> None:
    """Show current keywords with management keyboard."""
    chat_id = message.chat.id
    keywords = await get_user_keywords(chat_id)

    if not keywords:
        text = "🔑 У вас нет ключевых слов. Добавьте через кнопку ниже."
    else:
        text = (
            "🔑 <b>Ваши ключевые слова:</b>\n\n"
            + "\n".join(f"  • {kw}" for kw in keywords)
            + "\n\nНажмите ❌ чтобы удалить слово:"
        )

    await message.answer(
        text, parse_mode="HTML", reply_markup=keywords_keyboard(keywords)
    )


# ── /add <keyword> ───────────────────────────────────────────────────────────


@router.message(Command("add"))
async def cmd_add_keyword(message: Message) -> None:
    """Add a keyword from the command text: /add геодез."""
    chat_id = message.chat.id
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "⚠️ Укажите слово после команды.\n"
            "Пример: <code>/add геодез</code>",
            parse_mode="HTML",
        )
        return

    new_kw = parts[1].strip()
    keywords = await get_user_keywords(chat_id)

    if new_kw in keywords:
        await message.answer(f"ℹ️ Слово «{new_kw}» уже есть в списке.")
        return

    keywords.append(new_kw)
    await set_user_keywords(chat_id, keywords)
    await message.answer(
        f"✅ Добавлено: <b>{new_kw}</b>\n\n"
        f"Текущие слова: {', '.join(keywords)}",
        parse_mode="HTML",
    )


# ── /remove <keyword> ────────────────────────────────────────────────────────


@router.message(Command("remove"))
async def cmd_remove_keyword(message: Message) -> None:
    """Remove a keyword: /remove геодез."""
    chat_id = message.chat.id
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "⚠️ Укажите слово для удаления.\n"
            "Пример: <code>/remove геодез</code>",
            parse_mode="HTML",
        )
        return

    rm_kw = parts[1].strip()
    keywords = await get_user_keywords(chat_id)

    if rm_kw not in keywords:
        await message.answer(f"ℹ️ Слово «{rm_kw}» не найдено в списке.")
        return

    keywords.remove(rm_kw)
    await set_user_keywords(chat_id, keywords)
    await message.answer(
        f"🗑 Удалено: <b>{rm_kw}</b>\n\n"
        f"Текущие слова: {', '.join(keywords) if keywords else '(пусто)'}",
        parse_mode="HTML",
    )


# ── /status ──────────────────────────────────────────────────────────────────


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Show bot status and last poll stats."""
    last_run = _get_poll_stat_str("last_run", "ещё не запускался")
    found = _get_poll_stat_int("tenders_found")
    sent = _get_poll_stat_int("tenders_sent")
    errors = _get_poll_stat_int("errors")

    chat_id = message.chat.id
    keywords = await get_user_keywords(chat_id)

    status_text = (
        "📊 <b>Статус бота</b>\n\n"
        f"⏱ Интервал: каждые {settings.poll_interval_seconds} сек.\n"
        f"🕐 Последний запуск: {last_run}\n"
        f"🔍 Найдено тендеров: {found}\n"
        f"📨 Отправлено новых: {sent}\n"
        f"❌ Ошибок: {errors}\n\n"
        f"🔑 Ваши ключевые слова:\n{', '.join(keywords)}"
    )
    await message.answer(status_text, parse_mode="HTML")


# ── /stop & /resume ──────────────────────────────────────────────────────────


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    """Pause notifications for this user."""
    await set_user_enabled(message.chat.id, enabled=False)
    await message.answer("⏸ Уведомления приостановлены. /resume — чтобы возобновить.")


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    """Resume notifications for this user."""
    await set_user_enabled(message.chat.id, enabled=True)
    await message.answer("▶️ Уведомления возобновлены!")


# ── /help ────────────────────────────────────────────────────────────────────


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show available commands."""
    help_text = (
        "📖 <b>Доступные команды:</b>\n\n"
        "/start — Начать работу с ботом\n"
        "/keywords — Показать ключевые слова\n"
        "/add <i>слово</i> — Добавить ключевое слово\n"
        "/remove <i>слово</i> — Удалить ключевое слово\n"
        "/status — Статус бота\n"
        "/stop — Приостановить уведомления\n"
        "/resume — Возобновить уведомления\n"
        "/help — Эта справка"
    )
    await message.answer(help_text, parse_mode="HTML")


# ── Callback handlers (inline keyboard) ─────────────────────────────────────


@router.callback_query(F.data == "show_keywords")
async def cb_show_keywords(callback: CallbackQuery) -> None:
    """Show keywords via inline button."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return

    chat_id = msg.chat.id
    keywords = await get_user_keywords(chat_id)

    text = (
        "🔑 <b>Ваши ключевые слова:</b>\n\n"
        + "\n".join(f"  • {kw}" for kw in keywords)
        + "\n\nНажмите ❌ чтобы удалить слово:"
    )
    await msg.edit_text(
        text, parse_mode="HTML", reply_markup=keywords_keyboard(keywords)
    )
    await callback.answer()


@router.callback_query(F.data == "show_status")
async def cb_show_status(callback: CallbackQuery) -> None:
    """Show status via inline button."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return

    last_run = _get_poll_stat_str("last_run", "ещё не запускался")
    found = _get_poll_stat_int("tenders_found")
    sent = _get_poll_stat_int("tenders_sent")

    text = (
        "📊 <b>Статус бота</b>\n\n"
        f"⏱ Интервал: каждые {settings.poll_interval_seconds} сек.\n"
        f"🕐 Последний запуск: {last_run}\n"
        f"🔍 Найдено тендеров: {found}\n"
        f"📨 Отправлено новых: {sent}"
    )
    await msg.edit_text(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("rm_kw:"))
async def cb_remove_keyword(callback: CallbackQuery) -> None:
    """Remove a keyword via inline button."""
    msg = _get_callback_message(callback)
    if msg is None or callback.data is None:
        await callback.answer()
        return

    kw = callback.data.removeprefix("rm_kw:")
    chat_id = msg.chat.id
    keywords = await get_user_keywords(chat_id)

    if kw in keywords:
        keywords.remove(kw)
        await set_user_keywords(chat_id, keywords)

    text = (
        "🔑 <b>Ваши ключевые слова:</b>\n\n"
        + ("\n".join(f"  • {k}" for k in keywords) if keywords else "  (пусто)")
        + f"\n\n🗑 Удалено: {kw}"
    )
    await msg.edit_text(
        text, parse_mode="HTML", reply_markup=keywords_keyboard(keywords)
    )
    await callback.answer(f"Удалено: {kw}")


@router.callback_query(F.data == "add_kw")
async def cb_add_keyword_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt user to type a new keyword."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return

    await state.set_state(AddKeywordState.waiting_for_keyword)
    await msg.edit_text(
        "✏️ Введите новое ключевое слово для поиска:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddKeywordState.waiting_for_keyword)
async def handle_new_keyword(message: Message, state: FSMContext) -> None:
    """Receive the new keyword typed by the user."""
    new_kw = (message.text or "").strip()
    if not new_kw:
        await message.answer("⚠️ Введите непустое слово.")
        return

    chat_id = message.chat.id
    keywords = await get_user_keywords(chat_id)

    if new_kw in keywords:
        await message.answer(f"ℹ️ Слово «{new_kw}» уже есть в списке.")
    else:
        keywords.append(new_kw)
        await set_user_keywords(chat_id, keywords)
        await message.answer(
            f"✅ Добавлено: <b>{new_kw}</b>\n\n"
            f"Текущие слова: {', '.join(keywords)}",
            parse_mode="HTML",
            reply_markup=keywords_keyboard(keywords),
        )

    await state.clear()


@router.callback_query(F.data == "pause_notifications")
async def cb_pause(callback: CallbackQuery) -> None:
    """Pause notifications via inline button."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return

    await set_user_enabled(msg.chat.id, enabled=False)
    await msg.edit_text(
        "⏸ Уведомления приостановлены.\n\n"
        "Нажмите /resume или используйте меню /start чтобы возобновить.",
        parse_mode="HTML",
    )
    await callback.answer("Уведомления приостановлены")


@router.callback_query(F.data == "resume_notifications")
async def cb_resume(callback: CallbackQuery) -> None:
    """Resume notifications via inline button."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return

    await set_user_enabled(msg.chat.id, enabled=True)
    await msg.edit_text(
        "▶️ Уведомления возобновлены!\n\n"
        "Используйте /start для главного меню.",
        parse_mode="HTML",
    )
    await callback.answer("Уведомления возобновлены")


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery) -> None:
    """Generic cancel handler."""
    msg = _get_callback_message(callback)
    if msg is None:
        await callback.answer()
        return
    await msg.edit_text("❌ Отменено.")
    await callback.answer()
