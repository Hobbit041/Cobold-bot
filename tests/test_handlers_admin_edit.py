import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.admin_edit import (
    EditPollStates,
    apply_new_date,
    apply_new_text,
    select_action,
    select_option,
    select_poll,
    start_edit_poll,
)
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


async def test_edit_date_notifies_existing_voters(tmp_path, session_maker):
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
        FakeMessage("date"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )
    await apply_new_date(FakeMessage("25.07.2026"), state, bot=fake_bot, session_maker=session_maker)

    fake_bot.edit_message_text.assert_awaited_once()
    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24.07» перенесён с 24 июля на 25 июля.",
    )

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].date == dt.date(2026, 7, 25)

    assert await state.get_state() is None


async def test_edit_text_without_voters_sends_no_notification(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))])
        await repo.set_poll_message(session, poll.id, message_id=42)

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
    fake_bot.send_message.assert_not_awaited()

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "24.07 (в 19:00)"


async def test_edit_text_survives_refresh_failure_and_still_replies(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))])
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    fake_bot.edit_message_text.side_effect = Exception("message to edit not found")
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("text"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )
    final_message = FakeMessage("24.07 (в 19:00)")
    await apply_new_text(final_message, state, bot=fake_bot, session_maker=session_maker)

    # DB change was still applied despite the refresh failure.
    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "24.07 (в 19:00)"

    # FSM state was cleared, so a stale waiting_new_text handler can't
    # silently reinterpret the admin's next unrelated message.
    assert await state.get_state() is None
    assert await state.get_state() != EditPollStates.waiting_new_text.state

    # The admin got some reply rather than silence / an unhandled exception.
    final_message.answer.assert_awaited_once()


async def test_apply_new_text_shows_voter_names_for_all_options(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        edited_option, other_option = options
        await repo.toggle_vote(session, edited_option.id, user_id=5, username="alice", first_name="Alice")
        await repo.toggle_vote(session, other_option.id, user_id=6, username="bob", first_name="Bob")

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

    sent_text = fake_bot.edit_message_text.await_args.kwargs["text"]
    assert "1. 24.07 (в 19:00) (24 июля) — 1 🗳\n   @alice" in sent_text
    assert "2. 25.07 (25 июля) — 1 🗳\n   @bob" in sent_text
