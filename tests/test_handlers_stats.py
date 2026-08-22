import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from bot import repo
from bot.handlers.stats import handle_stats

TZ = ZoneInfo("Europe/Moscow")


class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = FakeUser(user_id)
        self.answer = AsyncMock()


class FakeResolvedChat:
    def __init__(self, title):
        self.title = title


async def test_handle_stats_non_admin_gets_help_text(session_maker):
    message = FakeMessage(user_id=2)
    fake_bot = AsyncMock()

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    text = message.answer.await_args.args[0]
    assert "/newpoll" in text
    assert "/editpoll" in text
    assert "/deletepoll" in text
    assert "/copypoll" in text
    assert "/checkme" in text
    assert "/cancel" in text
    assert "/stats" not in text
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_stats_admin_with_no_groups(session_maker):
    message = FakeMessage(user_id=1)
    fake_bot = AsyncMock()

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with("Бот пока не используется ни в одной группе.")


async def test_handle_stats_admin_lists_groups_with_last_poll_date(session_maker):
    async with session_maker() as session:
        poll_a = await repo.create_poll(session, chat_id=100, title="A", options=[("x", None)])
        poll_b = await repo.create_poll(session, chat_id=200, title="B", options=[("x", None)])
        poll_a.created_at = dt.datetime(2026, 8, 20, 10, 0, 0)
        poll_b.created_at = dt.datetime(2026, 8, 22, 10, 0, 0)
        await session.commit()

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = lambda chat_id: {
        100: FakeResolvedChat(title="Компания А"),
        200: FakeResolvedChat(title="Компания Б"),
    }[chat_id]
    message = FakeMessage(user_id=1)

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Бот используется в 2 групп(ах):\n"
        "«Компания Б» — последний опрос: 22 августа 2026\n"
        "«Компания А» — последний опрос: 20 августа 2026"
    )


async def test_handle_stats_admin_marks_unreachable_chat(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=999, title="C", options=[("x", None)])
        poll.created_at = dt.datetime(2026, 8, 1, 10, 0, 0)
        await session.commit()

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = RuntimeError("bot was removed from chat")
    message = FakeMessage(user_id=1)

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Бот используется в 1 групп(ах):\n"
        "«группа 999 (бот больше не состоит в ней)» — последний опрос: 1 августа 2026"
    )
