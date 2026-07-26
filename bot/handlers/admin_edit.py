"""Admin-only conversation flow for editing an existing poll via /editpoll.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo. Any pending 15-minute threshold-debounce timer is
cancelled through bot.scheduler when its option is deleted.
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

from bot import date_utils, formatting, keyboards, repo
from bot.handlers.dialog_cleanup import cleanup_and_answer
from bot.models import Poll
from bot.scheduler import cancel_threshold_check

router = Router(name="admin_edit")
logger = logging.getLogger(__name__)

_OPTION_GONE_MESSAGE = "Этот вариант больше недоступен (возможно, уже удалён)."
_PARTIAL_FAILURE_MESSAGE = (
    "Изменения сохранены в базе, но не удалось обновить сообщение в чате и/или "
    "уведомить проголосовавших. Проверьте опрос вручную."
)


class EditPollStates(StatesGroup):
    waiting_poll_selection = State()
    waiting_option_selection = State()
    waiting_action = State()
    waiting_new_text = State()
    waiting_new_date = State()
    waiting_new_option = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("editpoll"))
async def start_edit_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_answer(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
        await cleanup_and_answer(message, state, "Активных опросов нет.", scheduler=scheduler)
        return

    lines = [f"{i + 1}. {poll.title} (id={poll.id})" for i, poll in enumerate(polls)]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(EditPollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message, state, "Выберите опрос по номеру:\n" + "\n".join(lines), scheduler=scheduler
    )


@router.message(EditPollStates.waiting_poll_selection)
async def select_poll(message: Message, state: FSMContext, session_maker, scheduler=None) -> None:
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
        options = await repo.get_poll_options(session, poll_id)

    lines = [
        f"{i + 1}. {opt.text}" + (f" ({date_utils.format_date_ru(opt.date)})" if opt.date else "")
        for i, opt in enumerate(options)
    ]
    await state.update_data(poll_id=poll_id, option_ids=[opt.id for opt in options])
    await state.set_state(EditPollStates.waiting_option_selection)
    await cleanup_and_answer(
        message,
        state,
        "Выберите вариант по номеру, либо отправьте /addoption чтобы добавить новый:\n"
        + "\n".join(lines),
        scheduler=scheduler,
    )


@router.message(EditPollStates.waiting_option_selection, Command("addoption"))
async def start_add_option(message: Message, state: FSMContext, scheduler=None) -> None:
    await state.set_state(EditPollStates.waiting_new_option)
    await cleanup_and_answer(
        message,
        state,
        "Введите новый вариант в формате:\nТекст | ДД.ММ.ГГГГ (вместо | подойдёт и / или \\)",
        scheduler=scheduler,
    )


@router.message(EditPollStates.waiting_new_option)
async def receive_new_option(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    try:
        option_text, option_date = date_utils.parse_option_input(message.text or "")
    except date_utils.DateParseError as exc:
        await cleanup_and_answer(message, state, str(exc), scheduler=scheduler)
        return

    data = await state.get_data()
    poll_id = data["poll_id"]

    async with session_maker() as session:
        await repo.add_option(session, poll_id, option_text, option_date)
        poll = await repo.get_poll(session, poll_id)
        poll_options = await repo.get_poll_options(session, poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    # A brand-new option has no prior voters, so there's nothing to notify --
    # unlike edit/delete, only the poll message itself needs refreshing.
    success = await _refresh_and_notify(bot, poll, poll_options, counts, voters_by_option, [], None, session_maker)

    await state.clear()
    await cleanup_and_answer(
        message, state, "Вариант добавлен." if success else _PARTIAL_FAILURE_MESSAGE, scheduler=scheduler
    )


@router.message(EditPollStates.waiting_option_selection)
async def select_option(message: Message, state: FSMContext, scheduler=None) -> None:
    data = await state.get_data()
    option_ids = data["option_ids"]
    try:
        index = int(message.text.strip()) - 1
        if index < 0:
            raise IndexError
        option_id = option_ids[index]
    except (ValueError, IndexError, AttributeError):
        await cleanup_and_answer(
            message, state, "Некорректный номер. Попробуйте снова.", scheduler=scheduler
        )
        return

    await state.update_data(option_id=option_id)
    await state.set_state(EditPollStates.waiting_action)
    await cleanup_and_answer(
        message, state, "Что сделать с вариантом? Ответьте: text / date / delete", scheduler=scheduler
    )


@router.message(EditPollStates.waiting_action)
async def select_action(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    action = (message.text or "").strip().lower()
    data = await state.get_data()
    option_id = data["option_id"]

    if action == "text":
        await state.set_state(EditPollStates.waiting_new_text)
        await cleanup_and_answer(message, state, "Введите новый текст варианта:", scheduler=scheduler)
        return

    if action == "date":
        await state.set_state(EditPollStates.waiting_new_date)
        await cleanup_and_answer(message, state, "Введите новую дату (ДД.ММ.ГГГГ):", scheduler=scheduler)
        return

    if action == "delete":
        await _apply_delete(message, state, bot, session_maker, scheduler, option_id)
        return

    await cleanup_and_answer(
        message, state, "Не понял. Ответьте: text / date / delete", scheduler=scheduler
    )


@router.message(EditPollStates.waiting_new_text)
async def apply_new_text(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None) -> None:
    if not message.text:
        await cleanup_and_answer(message, state, "Пожалуйста, отправьте текст.", scheduler=scheduler)
        return

    data = await state.get_data()
    option_id = data["option_id"]
    new_text = message.text.strip()

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None:
            await state.clear()
            await cleanup_and_answer(message, state, _OPTION_GONE_MESSAGE, scheduler=scheduler)
            return

        old_text = option.text
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_text(session, option_id, new_text)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    notification_text = None
    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_text_changed_notification(old_text, new_text, mentions)

    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, voters, notification_text, session_maker
    )

    await state.clear()
    await cleanup_and_answer(
        message, state, "Вариант обновлён." if success else _PARTIAL_FAILURE_MESSAGE, scheduler=scheduler
    )


@router.message(EditPollStates.waiting_new_date)
async def apply_new_date(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None) -> None:
    if not message.text:
        await cleanup_and_answer(message, state, "Пожалуйста, отправьте дату.", scheduler=scheduler)
        return

    data = await state.get_data()
    option_id = data["option_id"]

    try:
        new_date = date_utils.parse_date_input(message.text.strip())
    except date_utils.DateParseError as exc:
        await cleanup_and_answer(message, state, str(exc), scheduler=scheduler)
        return

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None:
            await state.clear()
            await cleanup_and_answer(message, state, _OPTION_GONE_MESSAGE, scheduler=scheduler)
            return

        old_date = option.date
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_date(session, option_id, new_date)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    notification_text = None
    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_date_changed_notification(updated.text, old_date, new_date, mentions)

    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, voters, notification_text, session_maker
    )

    await state.clear()
    await cleanup_and_answer(
        message,
        state,
        "Дата варианта обновлена." if success else _PARTIAL_FAILURE_MESSAGE,
        scheduler=scheduler,
    )


async def _apply_delete(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler, option_id: int) -> None:
    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None:
            await state.clear()
            await cleanup_and_answer(message, state, _OPTION_GONE_MESSAGE, scheduler=scheduler)
            return

        option_text = option.text
        voters = await repo.get_voters(session, option_id)
        poll = await repo.get_poll(session, option.poll_id)
        await repo.delete_option(session, option_id)
        poll_options = await repo.get_poll_options(session, option.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    cancel_threshold_check(scheduler, option_id)

    notification_text = None
    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_deleted_notification(option_text, mentions)

    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, voters, notification_text, session_maker
    )

    await state.clear()
    await cleanup_and_answer(
        message, state, "Вариант удалён." if success else _PARTIAL_FAILURE_MESSAGE, scheduler=scheduler
    )


async def _refresh_and_notify(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
    voters,
    notification_text: str | None,
    session_maker,
) -> bool:
    """Refresh the live poll message and notify voters (if any).

    Both calls hit the Telegram API and can fail independently (e.g. the
    poll's message was manually deleted from the chat, or a transient error).
    Failures here must never propagate: callers rely on always reaching
    state.clear() and always answering the admin, so a bad network call
    doesn't strand the FSM in a state where the *next* unrelated admin
    message gets silently reinterpreted as new option text/date. Returns
    True only if both steps succeeded.
    """
    ok = True
    try:
        await _refresh_poll_message(bot, poll, poll_options, counts, voters_by_option, session_maker)
    except Exception:
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
        ok = False

    if voters and notification_text is not None:
        try:
            await bot.send_message(
                chat_id=poll.chat_id, text=notification_text, message_thread_id=poll.message_thread_id
            )
        except Exception:
            logger.exception("Failed to notify voters for poll %s", poll.id)
            ok = False

    return ok


async def _refresh_poll_message(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
    session_maker,
) -> None:
    lines = [
        formatting.format_option_line(
            i + 1, opt.text, opt.date, counts[opt.id], voters_by_option.get(opt.id, [])
        )
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, opt.date, counts[opt.id]) for opt in poll_options]
    )
    try:
        await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "not found" in exc.message.lower():
            async with session_maker() as session:
                await repo.mark_poll_orphaned(session, poll.id)
        raise
