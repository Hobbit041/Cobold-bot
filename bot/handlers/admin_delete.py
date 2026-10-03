"""/deletepoll: permanently delete a poll's database record and its live
Telegram message.

Works from any chat, including a DM with the bot (like /editpoll) -- the
message to delete is identified by the poll's own stored chat_id/message_id,
not by whatever chat the caller happens to run /deletepoll from. Available to
any user; the list of polls offered is filtered down to only those in chats
the requester administers/created (bot.authz.filter_by_chat_admin).
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import formatting, links, repo
from bot.authz import filter_by_chat_admin
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll

router = Router(name="admin_delete")
logger = logging.getLogger(__name__)

_POLL_MESSAGE_TOO_OLD = (
    "Опрос удалён из бота, но его сообщение осталось в чате: "
    f"{formatting.TOO_OLD_TO_DELETE} Удалите его вручную."
)
_POLL_MESSAGE_DELETE_FAILED = (
    "Опрос удалён из бота, но убрать его сообщение из чата не получилось — "
    "удалите его вручную."
)


class DeletePollStates(StatesGroup):
    waiting_poll_selection = State()


@router.message(Command("deletepoll"))
async def start_delete_poll(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    user_id = message.from_user.id if message.from_user is not None else None

    async with session_maker() as session:
        # Unlike /editpoll and /copypoll, deliberately not filtered to status
        # == "active" -- an already-"orphaned" poll must stay reachable here,
        # or it would be permanently unreachable/undeletable from any command.
        # If the bot has been removed from a poll's chat, the poll is filtered
        # out here via the chat-admin check below -- a known, accepted tradeoff.
        result = await session.execute(select(Poll))
        polls = list(result.scalars().all())

    polls = await filter_by_chat_admin(bot, polls, user_id, lambda p: p.chat_id)

    if not polls:
        await cleanup_and_finish(message, state, "Опросов нет.", scheduler=scheduler)
        return

    message_links = await links.poll_message_links(bot, polls)
    lines = [
        formatting.poll_choice_line(
            i + 1,
            poll.title,
            poll.id,
            message_links[poll.id],
            orphaned=poll.status == "orphaned",
        )
        for i, poll in enumerate(polls)
    ]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message,
        state,
        "Какой опрос удалить? Выберите по номеру:\n" + "\n".join(lines),
        scheduler=scheduler,
        parse_mode="HTML",
    )


@router.message(DeletePollStates.waiting_poll_selection)
async def select_poll_to_delete(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    data = await state.get_data()
    poll_ids = data["poll_ids"]
    try:
        index = int(message.text.strip()) - 1
        if index < 0:
            raise IndexError
        poll_id = poll_ids[index]
    except (ValueError, IndexError, AttributeError):
        await cleanup_and_answer(
            message, state, "Некорректный номер. Попробуйте снова.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        poll = await repo.get_poll(session, poll_id)
        if poll is None:
            await cleanup_and_finish(message, state, "Опрос уже удалён.", scheduler=scheduler)
            return
        chat_id = poll.chat_id
        message_id = poll.message_id

    # The DB record goes either way, including when the chat message survives:
    # a poll the bot can no longer delete the message for must still be
    # removable from the bot's own state, or it would clog the /editpoll,
    # /copypoll and /deletepoll listings forever. But say so instead of
    # reporting a clean "Опрос удалён." over a message still in the chat.
    text = "Опрос удалён."
    if message_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramBadRequest as error:
            if "not found" not in str(error).lower():
                text = _POLL_MESSAGE_TOO_OLD
            logger.warning(
                "Telegram refused to delete message %s in chat %s for poll %s: %s",
                message_id,
                chat_id,
                poll_id,
                error,
            )
        except Exception:
            text = _POLL_MESSAGE_DELETE_FAILED
            logger.exception(
                "Failed to delete message %s in chat %s for poll %s", message_id, chat_id, poll_id
            )

    async with session_maker() as session:
        await repo.delete_poll(session, poll_id)

    await cleanup_and_finish(message, state, text, scheduler=scheduler)
