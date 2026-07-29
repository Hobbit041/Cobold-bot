"""Admin-only /deletepoll: permanently delete a poll's database record and its
live Telegram message.

Works from any chat, including a DM with the bot (like /editpoll) -- the
message to delete is identified by the poll's own stored chat_id/message_id,
not by whatever chat the admin happens to run /deletepoll from.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import repo
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll

router = Router(name="admin_delete")
logger = logging.getLogger(__name__)


class DeletePollStates(StatesGroup):
    waiting_poll_selection = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("deletepoll"))
async def start_delete_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_finish(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        # Unlike /editpoll and /copypoll, deliberately not filtered to status
        # == "active" -- an already-"orphaned" poll must stay reachable here,
        # or it would be permanently unreachable/undeletable from any command.
        result = await session.execute(select(Poll))
        polls = list(result.scalars().all())

    if not polls:
        await cleanup_and_finish(message, state, "Опросов нет.", scheduler=scheduler)
        return

    lines = [
        f"{i + 1}. {poll.title} (id={poll.id})"
        + (" [опрос удалён, есть только в БД]" if poll.status == "orphaned" else "")
        for i, poll in enumerate(polls)
    ]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message,
        state,
        "Какой опрос удалить? Выберите по номеру:\n" + "\n".join(lines),
        scheduler=scheduler,
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

    if message_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.exception(
                "Failed to delete message %s in chat %s for poll %s", message_id, chat_id, poll_id
            )

    async with session_maker() as session:
        await repo.delete_poll(session, poll_id)

    await cleanup_and_finish(message, state, "Опрос удалён.", scheduler=scheduler)
