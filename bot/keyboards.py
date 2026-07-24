from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_poll_keyboard(options: list[tuple[int, str, int]]) -> InlineKeyboardMarkup:
    """options: list of (option_id, text, vote_count)."""
    builder = InlineKeyboardBuilder()
    for option_id, text, vote_count in options:
        builder.button(text=f"{text} ({vote_count})", callback_data=f"vote:{option_id}")
    builder.adjust(1)
    return builder.as_markup()
