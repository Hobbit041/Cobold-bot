"""Keeps multi-step admin dialogs (/newpoll, /editpoll) from cluttering
group chats, without changing behavior in private chats (DMs).
"""

from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

logger = logging.getLogger(__name__)


async def cleanup_and_answer(message: Message, state: FSMContext, text: str, **kwargs) -> Message:
    """Send the next step of an admin dialog.

    In any non-private chat: deletes the admin's triggering message and the
    bot's previous prompt (tracked in FSM data as last_bot_message_id)
    before sending the next prompt, so a multi-step conversation doesn't
    leave a trail of back-and-forth messages in the group. In private
    chats, does none of that -- a 1:1 history with the bot isn't clutter,
    and deleting there would be surprising.
    """
    if message.chat.type == "private":
        return await message.answer(text, **kwargs)

    data = await state.get_data()
    last_bot_message_id = data.get("last_bot_message_id")

    try:
        await message.delete()
    except Exception:
        logger.exception(
            "Failed to delete admin message %s in chat %s", message.message_id, message.chat.id
        )

    if last_bot_message_id is not None:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message_id)
        except Exception:
            logger.exception(
                "Failed to delete previous bot prompt %s in chat %s", last_bot_message_id, message.chat.id
            )

    sent = await message.answer(text, **kwargs)
    await state.update_data(last_bot_message_id=sent.message_id)
    return sent
