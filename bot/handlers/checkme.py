from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, repo

router = Router(name="checkme")


@router.message(Command("checkme"))
async def handle_checkme(message: Message, bot: Bot, session_maker) -> None:
    user = message.from_user
    if user is None:
        return

    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id)

    mention = formatting.voter_mention(user.username, user.first_name)

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

        lines.append(formatting.checkme_line(len(lines) + 1, option.text, option.date, chat.title, link))

    if not lines:
        await message.answer(formatting.checkme_empty_text(mention), parse_mode="HTML")
        return

    text = formatting.checkme_header(mention) + "\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")
