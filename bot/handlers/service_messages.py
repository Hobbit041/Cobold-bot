"""Tracks Telegram's own service notices (member joined/left, chat pinned a
message, title/photo changed, forum topic events, ...) as they happen, so
/clear can delete them later.

Telegram's Bot API gives bots no way to list or fetch a chat's past messages
-- deleteMessage only works on a message_id the bot already knows. So /clear
can only ever clean up service messages recorded from the moment this router
starts running; anything from before is unreachable.

Must be included in the Dispatcher before admin_create/admin_edit/admin_copy/
admin_delete's routers, for the same reason dialog_control is (see its module
docstring): if an admin mid-dialog triggers a tracked service message in the
same chat (e.g. adds a member), a per-FSM-state catch-all handler in those
routers would otherwise swallow it before this router's content-type filter
runs.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot import formatting, repo
from bot.authz import is_chat_admin
from bot.handlers.dialog_cleanup import cleanup_and_finish

logger = logging.getLogger(__name__)

router = Router(name="service_messages")

_NOT_CHAT_ADMIN_MESSAGE = "Эта команда доступна только администраторам этого чата."
_PRIVATE_CHAT_MESSAGE = "Эта команда работает только в группах."

# Routine Telegram-generated notices worth silently clearing out later.
# Deliberately excludes anything with content a group might want kept:
# payments/gifts/giveaways/passport data, and migrate_to/from_chat_id (the
# chat's own id changes when that happens, which is worth leaving visible).
TRACKED_CONTENT_TYPES = {
    ContentType.NEW_CHAT_MEMBERS,
    ContentType.LEFT_CHAT_MEMBER,
    ContentType.CHAT_OWNER_LEFT,
    ContentType.CHAT_OWNER_CHANGED,
    ContentType.NEW_CHAT_TITLE,
    ContentType.NEW_CHAT_PHOTO,
    ContentType.DELETE_CHAT_PHOTO,
    ContentType.GROUP_CHAT_CREATED,
    ContentType.SUPERGROUP_CHAT_CREATED,
    ContentType.CHANNEL_CHAT_CREATED,
    ContentType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
    ContentType.PINNED_MESSAGE,
    ContentType.WRITE_ACCESS_ALLOWED,
    ContentType.PROXIMITY_ALERT_TRIGGERED,
    ContentType.BOOST_ADDED,
    ContentType.CHAT_BACKGROUND_SET,
    ContentType.FORUM_TOPIC_CREATED,
    ContentType.FORUM_TOPIC_EDITED,
    ContentType.FORUM_TOPIC_CLOSED,
    ContentType.FORUM_TOPIC_REOPENED,
    ContentType.GENERAL_FORUM_TOPIC_HIDDEN,
    ContentType.GENERAL_FORUM_TOPIC_UNHIDDEN,
    ContentType.VIDEO_CHAT_SCHEDULED,
    ContentType.VIDEO_CHAT_STARTED,
    ContentType.VIDEO_CHAT_ENDED,
    ContentType.VIDEO_CHAT_PARTICIPANTS_INVITED,
}


@router.message(F.content_type.in_(TRACKED_CONTENT_TYPES))
async def track_service_message(message: Message, session_maker) -> None:
    async with session_maker() as session:
        await repo.record_service_message(
            session, message.chat.id, message.message_thread_id, message.message_id
        )


@router.message(Command("clear"))
async def handle_clear(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    if message.chat.type == "private":
        await message.answer(_PRIVATE_CHAT_MESSAGE)
        return

    user_id = message.from_user.id if message.from_user is not None else None
    if user_id is None or not await is_chat_admin(bot, message.chat.id, user_id):
        await cleanup_and_finish(message, state, _NOT_CHAT_ADMIN_MESSAGE, scheduler=scheduler)
        return

    async with session_maker() as session:
        message_ids = await repo.pop_service_messages(
            session, message.chat.id, message.message_thread_id
        )

    deleted_count = 0
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message_id)
            deleted_count += 1
        except Exception:
            logger.exception(
                "Failed to delete service message %s in chat %s", message_id, message.chat.id
            )

    text = formatting.cleared_service_messages_text(deleted_count)
    await cleanup_and_finish(message, state, text, scheduler=scheduler)
