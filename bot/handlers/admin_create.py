"""Admin-only conversation flow for creating a new poll via /newpoll.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo.
"""

from __future__ import annotations

import datetime as dt
import re

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import date_utils, formatting, keyboards, repo
from bot.handlers.dialog_cleanup import cleanup_and_answer

router = Router(name="admin_create")

# Splits "Текст | ДД.ММ.ГГГГ" (and the /, \ variants) at the first separator.
_OPTION_SEPARATOR_PATTERN = re.compile(r"[|/\\]")


class CreatePollStates(StatesGroup):
    waiting_title = State()
    waiting_options = State()
    waiting_chat = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("newpoll"))
async def start_create_poll(message: Message, state: FSMContext, admin_id: int, scheduler=None) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_answer(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    await state.set_state(CreatePollStates.waiting_title)
    data = {"options": []}
    if message.chat.type != "private":
        # /newpoll was run directly in the target chat -- no need to ask
        # for it later. Also remember the forum topic (if any): posting a
        # NEW message into a forum-enabled group without message_thread_id
        # lands it in "General" instead of the topic the admin is in.
        data["target_chat_id"] = message.chat.id
        data["target_message_thread_id"] = message.message_thread_id
    await state.update_data(**data)
    await cleanup_and_answer(message, state, "Введите название опроса:", scheduler=scheduler)


@router.message(CreatePollStates.waiting_title)
async def receive_title(message: Message, state: FSMContext, scheduler=None) -> None:
    if not message.text:
        await cleanup_and_answer(
            message, state, "Пожалуйста, отправьте текстовое название.", scheduler=scheduler
        )
        return

    await state.update_data(title=message.text)
    await state.set_state(CreatePollStates.waiting_options)
    await cleanup_and_answer(
        message,
        state,
        "Теперь добавляйте варианты по одному в формате:\n"
        "Текст | ДД.ММ.ГГГГ (вместо | подойдёт и / или \\)\n"
        "Когда закончите — отправьте /done",
        scheduler=scheduler,
    )


@router.message(CreatePollStates.waiting_options, Command("done"))
async def finish_options(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None) -> None:
    data = await state.get_data()
    options = data.get("options", [])
    if not options:
        await cleanup_and_answer(
            message, state, "Нужно добавить хотя бы один вариант перед /done.", scheduler=scheduler
        )
        return

    target_chat_id = data.get("target_chat_id")
    if target_chat_id is not None:
        await _create_and_publish_poll(
            message,
            state,
            bot,
            session_maker,
            target_chat_id,
            data.get("target_message_thread_id"),
            scheduler=scheduler,
        )
        return

    await state.set_state(CreatePollStates.waiting_chat)
    await cleanup_and_answer(
        message,
        state,
        "Перешлите любое сообщение из целевого чата, либо пришлите его chat id.",
        scheduler=scheduler,
    )


@router.message(CreatePollStates.waiting_options)
async def receive_option(message: Message, state: FSMContext, scheduler=None) -> None:
    match = _OPTION_SEPARATOR_PATTERN.search(message.text) if message.text else None
    if not match:
        await cleanup_and_answer(
            message,
            state,
            "Формат: Текст | ДД.ММ.ГГГГ (вместо | подойдёт и / или \\). Попробуйте снова.",
            scheduler=scheduler,
        )
        return

    text_part = message.text[: match.start()]
    date_part = message.text[match.end():]
    text_part = text_part.strip()
    try:
        parsed_date = date_utils.parse_date_input(date_part.strip())
    except date_utils.DateParseError as exc:
        await cleanup_and_answer(message, state, str(exc), scheduler=scheduler)
        return

    data = await state.get_data()
    options = data.get("options", [])
    options.append({"text": text_part, "date": parsed_date.isoformat()})
    await state.update_data(options=options)
    await cleanup_and_answer(
        message,
        state,
        f"Добавлено: {text_part} ({date_utils.format_date_ru(parsed_date)}). Ещё вариант или /done.",
        scheduler=scheduler,
    )


@router.message(CreatePollStates.waiting_chat)
async def receive_target_chat(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None) -> None:
    chat_id = None
    forward_origin = getattr(message, "forward_origin", None)
    if forward_origin is not None and hasattr(forward_origin, "chat"):
        chat_id = forward_origin.chat.id
    elif getattr(message, "forward_from_chat", None) is not None:
        chat_id = message.forward_from_chat.id
    elif message.text:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            chat_id = None

    if chat_id is None:
        await cleanup_and_answer(
            message,
            state,
            "Не удалось определить чат. Перешлите сообщение из чата или пришлите его id.",
            scheduler=scheduler,
        )
        return

    await _create_and_publish_poll(message, state, bot, session_maker, chat_id, scheduler=scheduler)


async def _create_and_publish_poll(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session_maker,
    chat_id: int,
    message_thread_id: int | None = None,
    scheduler=None,
) -> None:
    data = await state.get_data()
    title = data["title"]
    options = [(opt["text"], dt.date.fromisoformat(opt["date"])) for opt in data["options"]]

    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=chat_id,
            title=title,
            options=options,
            message_thread_id=message_thread_id,
        )
        poll_options = await repo.get_poll_options(session, poll.id)
        lines = [
            formatting.format_option_line(i + 1, opt.text, opt.date, 0)
            for i, opt in enumerate(poll_options)
        ]
        text = formatting.poll_message_text(title, lines)
        keyboard = keyboards.build_poll_keyboard([(opt.id, opt.text, opt.date, 0) for opt in poll_options])

        try:
            sent = await bot.send_message(
                chat_id=chat_id, text=text, reply_markup=keyboard, message_thread_id=message_thread_id
            )
        except Exception:
            await session.delete(poll)
            await session.commit()
            if message.chat.type == "private":
                await cleanup_and_answer(
                    message,
                    state,
                    "Не удалось отправить опрос в этот чат. Проверьте, что бот добавлен в чат "
                    "и id указан верно, затем пришлите чат ещё раз.",
                    scheduler=scheduler,
                )
            else:
                await cleanup_and_answer(
                    message,
                    state,
                    "Не удалось опубликовать опрос в этом чате. Проверьте, что у бота есть права "
                    "отправлять сообщения, и повторите /done.",
                    scheduler=scheduler,
                )
            return

        await repo.set_poll_message(session, poll.id, sent.message_id)

    await state.clear()
    await cleanup_and_answer(message, state, "Опрос создан и опубликован!", scheduler=scheduler)
