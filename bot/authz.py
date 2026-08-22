"""Chat-scoped authorization checks shared by the poll-management handlers.

Replaces the old single-hardcoded-ADMIN_ID gate: instead of one allow-listed
user, any command that manages a poll checks whether the caller is an
admin/creator of that poll's own chat (via Telegram's own membership data),
so the bot works for any group without a central allow-list.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from aiogram import Bot

T = TypeVar("T")


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """True if user_id is an administrator or creator of chat_id.

    Any failure to look up membership (bot not in the chat, chat gone, etc.)
    is treated as "not authorized" rather than propagating -- callers must
    fail closed, not open.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("administrator", "creator")


async def filter_by_chat_admin(
    bot: Bot, items: list[T], user_id: int | None, chat_id_getter: Callable[[T], int]
) -> list[T]:
    """Keep only the items whose chat (via chat_id_getter) user_id administers.

    Each distinct chat is checked only once no matter how many items map to
    it, so filtering N polls across 2 chats costs 2 get_chat_member calls.
    """
    if user_id is None:
        return []

    cache: dict[int, bool] = {}
    kept: list[T] = []
    for item in items:
        chat_id = chat_id_getter(item)
        if chat_id not in cache:
            cache[chat_id] = await is_chat_admin(bot, chat_id, user_id)
        if cache[chat_id]:
            kept.append(item)
    return kept
