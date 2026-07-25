"""Keeps multi-step admin dialogs (/newpoll, /editpoll) from cluttering
group chats, without changing behavior in private chats (DMs).
"""

from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.jobs import expire_dialog
from bot.scheduler import cancel_dialog_timeout, schedule_dialog_timeout

logger = logging.getLogger(__name__)


async def cleanup_and_answer(
    message: Message, state: FSMContext, text: str, scheduler=None, **kwargs
) -> Message:
    """Send the next step of an admin dialog.

    In any non-private chat: deletes the admin's triggering message and the
    bot's previous prompt (tracked in FSM data as last_bot_message_id)
    before sending the next prompt, so a multi-step conversation doesn't
    leave a trail of back-and-forth messages in the group. In private
    chats, does none of that -- a 1:1 history with the bot isn't clutter,
    and deleting there would be surprising.

    If `scheduler` is given (it's always passed by real handlers; tests that
    don't care about the timeout may omit it), this also (re)arms a 5-minute
    idle timeout that force-exits the dialog via bot.jobs.expire_dialog --
    otherwise an admin who abandons a group dialog mid-flow would have every
    later unrelated message in that chat swallowed and rejected as invalid
    input forever. A message that leaves the FSM state cleared (the dialog's
    last step) cancels the pending timeout instead of rescheduling it.
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

    if scheduler is not None and message.from_user is not None:
        chat_id = message.chat.id
        user_id = message.from_user.id
        if await state.get_state() is None:
            cancel_dialog_timeout(scheduler, chat_id, user_id)
        else:
            schedule_dialog_timeout(
                scheduler, chat_id, user_id, message.message_thread_id, callback=expire_dialog
            )

    return sent
