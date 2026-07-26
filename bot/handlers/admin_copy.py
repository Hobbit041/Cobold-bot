"""Admin-only /copypoll: copy an existing poll's title and options into the
chat/topic where the command is run.

Only works when run directly in a group (never in a private chat with the
bot) -- unlike /newpoll's DM flow, there's no step here that lets a private
conversation express *which* chat/topic the copy should be published into.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import repo
from bot.handlers.admin_create import create_and_publish_poll
from bot.handlers.dialog_cleanup import cleanup_and_answer
from bot.models import Poll

router = Router(name="admin_copy")


class CopyPollStates(StatesGroup):
    waiting_poll_selection = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("copypoll"))
async def start_copy_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_answer(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    if message.chat.type == "private":
        await cleanup_and_answer(
            message,
            state,
            "Эта команда работает только в группе, в теме которую нужно скопировать опрос.",
            scheduler=scheduler,
        )
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
        await cleanup_and_answer(message, state, "Активных опросов нет.", scheduler=scheduler)
        return

    lines = [f"{i + 1}. {poll.title} (id={poll.id})" for i, poll in enumerate(polls)]
    await state.update_data(
        poll_ids=[poll.id for poll in polls],
        target_chat_id=message.chat.id,
        target_message_thread_id=message.message_thread_id,
    )
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message,
        state,
        "Какой опрос скопировать? Выберите по номеру:\n" + "\n".join(lines),
        scheduler=scheduler,
    )


@router.message(CopyPollStates.waiting_poll_selection)
async def select_poll_to_copy(
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
        source_poll = await repo.get_poll(session, poll_id)
        source_options = await repo.get_poll_options(session, poll_id)
        title = source_poll.title
        options = [(opt.text, opt.date) for opt in source_options]

    await create_and_publish_poll(
        message,
        state,
        bot,
        session_maker,
        data["target_chat_id"],
        title,
        options,
        data["target_message_thread_id"],
        scheduler=scheduler,
    )
