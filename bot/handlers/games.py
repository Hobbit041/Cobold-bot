"""`/games`: list games that "gathered" (4+ voters on a dated option).

In a group/topic, scoped to that chat only -- any member can run it, same
openness as /checkme. In a private chat with the bot there's no chat to scope
to, so it only works for an admin (checked the same way as
bot.authz.is_chat_admin/filter_by_chat_admin -- an admin/creator of at least
one chat that has polls), and even then only shows games from the chats they
administer. A plain user in DM, or an admin of no chat with polls, gets a
refusal -- this command must never leak one chat's game list to someone
without standing in that chat.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, keyboards, repo
from bot.authz import filter_by_chat_admin
from bot.handlers.checkme import build_dated_option_lines

logger = logging.getLogger(__name__)

router = Router(name="games")

MIN_GATHERED_VOTES = 4


@router.message(Command("games"))
async def handle_games(message: Message, bot: Bot, session_maker) -> None:
    user = message.from_user
    if user is None:
        return

    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete /games command message %s", message.message_id)

    if message.chat.type == "private":
        async with session_maker() as session:
            chat_stats = await repo.get_chat_poll_stats(session)
        chat_ids = await filter_by_chat_admin(
            bot, [chat_id for chat_id, _ in chat_stats], user.id, lambda chat_id: chat_id
        )
        if not chat_ids:
            await message.answer(formatting.games_not_available_in_dm_text())
            return
    else:
        chat_ids = [message.chat.id]

    async with session_maker() as session:
        rows = await repo.get_dated_options_for_chats(session, chat_ids)
        vote_counts = {option.id: await repo.get_vote_count(session, option.id) for _, option in rows}

    gathered = [row for row in rows if vote_counts[row[1].id] >= MIN_GATHERED_VOTES]
    lines = await build_dated_option_lines(bot, gathered, vote_counts)

    keyboard = keyboards.build_delete_keyboard(user.id)
    if not lines:
        await message.answer(formatting.games_empty_text(), parse_mode="HTML", reply_markup=keyboard)
        return

    text = formatting.games_header() + "\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
