"""Turning a poll's stored (chat_id, message_id) into a t.me link.

The URL shapes themselves live in bot.formatting.build_message_link, which is
pure. This module is the part that needs the Bot: only get_chat knows whether a
chat has an @username, which is what decides between the two forms.

A poll is treated as unlinkable -- link None, callers fall back to plain text --
when the bot never recorded a message id for it, or when the poll is "orphaned",
meaning its message is already gone from the chat (see
bot.handlers.admin_edit._refresh_poll_message). Linking an orphaned poll would
hand the admin a link to a message that no longer exists.
"""

from __future__ import annotations

import logging

from bot import formatting

logger = logging.getLogger(__name__)


async def _chat_username(bot, chat_id: int, cache: dict[int, str | None]) -> str | None:
    """The chat's @username, or None -- including when the lookup fails.

    A failed get_chat is not fatal: build_message_link still has the
    t.me/c/<internal id>/<message id> form for a supergroup, which is the
    common case, and callers cope with no link at all.
    """
    if chat_id not in cache:
        try:
            cache[chat_id] = (await bot.get_chat(chat_id)).username
        except Exception:
            logger.exception("Failed to look up chat %s for a message link", chat_id)
            cache[chat_id] = None
    return cache[chat_id]


async def poll_message_link(bot, chat_id: int, message_id: int | None) -> str | None:
    """Link to one poll message, or None if it has no addressable t.me form."""
    if message_id is None:
        return None
    return formatting.build_message_link(
        chat_id, message_id, await _chat_username(bot, chat_id, {})
    )


async def poll_message_links(bot, polls) -> dict[int, str | None]:
    """Links for a list of polls, keyed by poll id.

    One get_chat per distinct chat, however many of the polls live in it --
    /editpoll's and /deletepoll's listings routinely span several chats.
    """
    cache: dict[int, str | None] = {}
    links: dict[int, str | None] = {}

    for poll in polls:
        if poll.message_id is None or poll.status == "orphaned":
            links[poll.id] = None
            continue
        links[poll.id] = formatting.build_message_link(
            poll.chat_id, poll.message_id, await _chat_username(bot, poll.chat_id, cache)
        )

    return links
