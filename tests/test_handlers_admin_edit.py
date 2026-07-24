import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.admin_edit import apply_new_text, select_action, select_option, select_poll, start_edit_poll
from bot.scheduler import create_scheduler


class FakeMessage:
    def __init__(self, text, user_id=1):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
        self.answer = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


async def test_edit_text_notifies_existing_voters(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))])
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("text"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )
    await apply_new_text(FakeMessage("24.07 (в 19:00)"), state, bot=fake_bot, session_maker=session_maker)

    fake_bot.edit_message_text.assert_awaited_once()
    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! В опрос внесены изменения: «24.07» → «24.07 (в 19:00)».",
    )

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "24.07 (в 19:00)"


async def test_delete_option_notifies_and_removes_it(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        target_option = options[0]
        await repo.toggle_vote(session, target_option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("delete"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! В опрос внесены изменения: вариант «24.07» удалён.",
    )

    async with session_maker() as session:
        remaining = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in remaining] == ["25.07"]
