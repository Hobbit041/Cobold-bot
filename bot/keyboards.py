from __future__ import annotations

import datetime as dt

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.date_utils import format_date_ru


def build_poll_keyboard(options: list[tuple[int, str, dt.date | None, int]]) -> InlineKeyboardMarkup:
    """options: list of (option_id, text, date, vote_count)."""
    builder = InlineKeyboardBuilder()
    for option_id, text, date, vote_count in options:
        date_part = f" ({format_date_ru(date)})" if date is not None else ""
        label = f"{text}{date_part} — {vote_count}"
        builder.button(text=label, callback_data=f"vote:{option_id}")
    builder.adjust(1)
    return builder.as_markup()
