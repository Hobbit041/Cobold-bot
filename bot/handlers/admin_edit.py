"""Admin-only conversation flow for editing an existing poll via /editpoll.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo. Any pending 15-minute threshold-debounce timer is
cancelled through bot.scheduler when its option is deleted.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import date_utils, formatting, keyboards, repo
from bot.models import Poll
from bot.scheduler import cancel_threshold_check

router = Router(name="admin_edit")


class EditPollStates(StatesGroup):
    waiting_poll_selection = State()
    waiting_option_selection = State()
    waiting_action = State()
    waiting_new_text = State()
    waiting_new_date = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("editpoll"))
async def start_edit_poll(message: Message, state: FSMContext, admin_id: int, session_maker) -> None:
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда доступна только администратору.")
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
        await message.answer("Активных опросов нет.")
        return

    lines = [f"{i + 1}. {poll.title} (id={poll.id})" for i, poll in enumerate(polls)]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(EditPollStates.waiting_poll_selection)
    await message.answer("Выберите опрос по номеру:\n" + "\n".join(lines))


@router.message(EditPollStates.waiting_poll_selection)
async def select_poll(message: Message, state: FSMContext, session_maker) -> None:
    data = await state.get_data()
    poll_ids = data["poll_ids"]
    try:
        index = int(message.text.strip()) - 1
        poll_id = poll_ids[index]
    except (ValueError, IndexError, AttributeError):
        await message.answer("Некорректный номер. Попробуйте снова.")
        return

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll_id)

    lines = [f"{i + 1}. {opt.text} ({date_utils.format_date_ru(opt.date)})" for i, opt in enumerate(options)]
    await state.update_data(poll_id=poll_id, option_ids=[opt.id for opt in options])
    await state.set_state(EditPollStates.waiting_option_selection)
    await message.answer("Выберите вариант по номеру:\n" + "\n".join(lines))


@router.message(EditPollStates.waiting_option_selection)
async def select_option(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    option_ids = data["option_ids"]
    try:
        index = int(message.text.strip()) - 1
        option_id = option_ids[index]
    except (ValueError, IndexError, AttributeError):
        await message.answer("Некорректный номер. Попробуйте снова.")
        return

    await state.update_data(option_id=option_id)
    await state.set_state(EditPollStates.waiting_action)
    await message.answer("Что сделать с вариантом? Ответьте: text / date / delete")


@router.message(EditPollStates.waiting_action)
async def select_action(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler) -> None:
    action = (message.text or "").strip().lower()
    data = await state.get_data()
    option_id = data["option_id"]

    if action == "text":
        await state.set_state(EditPollStates.waiting_new_text)
        await message.answer("Введите новый текст варианта:")
        return

    if action == "date":
        await state.set_state(EditPollStates.waiting_new_date)
        await message.answer("Введите новую дату (ДД.ММ.ГГГГ):")
        return

    if action == "delete":
        await _apply_delete(message, state, bot, session_maker, scheduler, option_id)
        return

    await message.answer("Не понял. Ответьте: text / date / delete")


@router.message(EditPollStates.waiting_new_text)
async def apply_new_text(message: Message, state: FSMContext, bot: Bot, session_maker) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправьте текст.")
        return

    data = await state.get_data()
    option_id = data["option_id"]
    new_text = message.text.strip()

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        old_text = option.text
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_text(session, option_id, new_text)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        await bot.send_message(
            chat_id=poll.chat_id, text=formatting.option_text_changed_notification(old_text, new_text, mentions)
        )

    await state.clear()
    await message.answer("Вариант обновлён.")


@router.message(EditPollStates.waiting_new_date)
async def apply_new_date(message: Message, state: FSMContext, bot: Bot, session_maker) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправьте дату.")
        return

    data = await state.get_data()
    option_id = data["option_id"]

    try:
        new_date = date_utils.parse_date_input(message.text.strip())
    except date_utils.DateParseError as exc:
        await message.answer(str(exc))
        return

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        old_date = option.date
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_date(session, option_id, new_date)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        text = formatting.option_date_changed_notification(updated.text, old_date, new_date, mentions)
        await bot.send_message(chat_id=poll.chat_id, text=text)

    await state.clear()
    await message.answer("Дата варианта обновлена.")


async def _apply_delete(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler, option_id: int) -> None:
    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        option_text = option.text
        voters = await repo.get_voters(session, option_id)
        poll = await repo.get_poll(session, option.poll_id)
        await repo.delete_option(session, option_id)
        poll_options = await repo.get_poll_options(session, option.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    cancel_threshold_check(scheduler, option_id)
    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        await bot.send_message(chat_id=poll.chat_id, text=formatting.option_deleted_notification(option_text, mentions))

    await state.clear()
    await message.answer("Вариант удалён.")


async def _refresh_poll_message(bot: Bot, poll: Poll, poll_options, counts: dict[int, int]) -> None:
    lines = [
        formatting.format_option_line(i + 1, opt.text, opt.date, counts[opt.id])
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard([(opt.id, opt.text, counts[opt.id]) for opt in poll_options])
    await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
