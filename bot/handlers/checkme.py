from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, repo

router = Router(name="checkme")


async def _build_lines(bot: Bot, rows: list[tuple[repo.Poll, repo.Option]]) -> list[str]:
    chat_cache: dict[int, object | None] = {}
    lines: list[str] = []
    for poll, option in rows:
        if poll.message_id is None:
            continue

        if poll.chat_id not in chat_cache:
            try:
                chat_cache[poll.chat_id] = await bot.get_chat(poll.chat_id)
            except Exception:
                chat_cache[poll.chat_id] = None
        chat = chat_cache[poll.chat_id]

        if chat is None or not chat.title:
            continue

        link = formatting.build_message_link(poll.chat_id, poll.message_id, chat.username)
        if link is None:
            continue

        lines.append(formatting.record_line(len(lines) + 1, option.text, option.date, chat.title, link))
    return lines


async def _answer_with_lines(message: Message, lines: list[str], header: str, empty_text: str) -> None:
    if not lines:
        await message.answer(empty_text, parse_mode="HTML")
        return

    text = header + "\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("checkme"))
async def handle_checkme(message: Message, bot: Bot, session_maker, timezone: ZoneInfo) -> None:
    user = message.from_user
    if user is None:
        return

    today = dt.datetime.now(timezone).date()
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id, on_or_after=today)

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows)
    await _answer_with_lines(
        message, lines, formatting.checkme_header(mention), formatting.checkme_empty_text(mention)
    )


@router.message(Command("mygames"))
async def handle_mygames(message: Message, bot: Bot, session_maker, timezone: ZoneInfo) -> None:
    user = message.from_user
    if user is None:
        return

    today = dt.datetime.now(timezone).date()
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id, before=today)

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows)
    await _answer_with_lines(
        message, lines, formatting.mygames_header(mention), formatting.mygames_empty_text(mention)
    )
