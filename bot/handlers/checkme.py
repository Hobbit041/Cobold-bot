from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, repo

router = Router(name="checkme")


async def _build_lines(
    bot: Bot, rows: list[tuple[repo.Poll, repo.Option]], vote_counts: dict[int, int]
) -> list[str]:
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

        lines.append(
            formatting.record_line(
                len(lines) + 1, option.text, option.date, chat.title, vote_counts[option.id], link
            )
        )
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
        vote_counts = {option.id: await repo.get_vote_count(session, option.id) for _, option in rows}

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows, vote_counts)
    await _answer_with_lines(
        message, lines, formatting.checkme_header(mention), formatting.checkme_empty_text(mention)
    )


# Implemented and tested, but intentionally not wired to a Command filter:
# /deletepoll purges votes outright, so /mygames can never show history for
# polls removed that way -- disabled until players actually ask for it.
async def handle_mygames(message: Message, bot: Bot, session_maker, timezone: ZoneInfo) -> None:
    user = message.from_user
    if user is None:
        return

    today = dt.datetime.now(timezone).date()
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id, before=today)
        vote_counts = {option.id: await repo.get_vote_count(session, option.id) for _, option in rows}

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows, vote_counts)
    await _answer_with_lines(
        message, lines, formatting.mygames_header(mention), formatting.mygames_empty_text(mention)
    )
