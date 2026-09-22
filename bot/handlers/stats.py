"""`/stats`: developer-only usage overview; everyone else gets a command list.

ADMIN_ID from `.env` is no longer used to gate poll management -- it's kept
purely so the bot's developer can send /stats and see which chats the bot
has been used in and when each last saw a poll created. Anyone else who
sends /stats gets a short list of available commands instead.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import date_utils, repo

router = Router(name="stats")

_HELP_TEXT = (
    "Этот бот помогает организовывать опросы по датам в группах.\n"
    "\n"
    "Доступные команды:\n"
    "/newpoll — создать новый опрос\n"
    "/editpoll — изменить опрос (текст/дату варианта, добавить вариант, порядок, название)\n"
    "/deletepoll — удалить опрос полностью\n"
    "/copypoll — скопировать существующий опрос в текущий чат\n"
    "/checkme — посмотреть, на какие предстоящие игры вы записаны\n"
    "/games — список собравшихся игр (4+ игрока) в этом чате\n"
    "/cancel — отменить текущий диалог с ботом\n"
    "\n"
    "Управление опросами (/newpoll, /editpoll, /deletepoll, /copypoll) доступно "
    "только администраторам группы. Чтобы бот мог публиковать и обновлять "
    "опросы, добавьте его в группу и выдайте права администратора."
)

_NO_GROUPS_TEXT = "Бот пока не используется ни в одной группе."


async def _describe_chat(bot: Bot, chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        return chat.title or str(chat_id)
    except Exception:
        return f"группа {chat_id} (бот больше не состоит в ней)"


@router.message(Command("stats"))
async def handle_stats(
    message: Message, bot: Bot, session_maker, admin_id: int, timezone: ZoneInfo
) -> None:
    user = message.from_user
    if user is None:
        return

    if user.id != admin_id:
        await message.answer(_HELP_TEXT)
        return

    async with session_maker() as session:
        rows = await repo.get_chat_poll_stats(session)

    if not rows:
        await message.answer(_NO_GROUPS_TEXT)
        return

    lines = []
    for chat_id, last_created_at in rows:
        title = await _describe_chat(bot, chat_id)
        local_date = last_created_at.replace(tzinfo=dt.timezone.utc).astimezone(timezone).date()
        lines.append(f"«{title}» — последний опрос: {date_utils.format_date_ru_with_year(local_date)}")

    text = f"Бот используется в {len(rows)} групп(ах):\n" + "\n".join(lines)
    await message.answer(text)
