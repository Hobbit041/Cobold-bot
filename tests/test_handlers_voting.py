import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from bot import repo
from bot.handlers.voting import handle_vote_toggle
from bot.scheduler import create_scheduler, threshold_job_id


class FakeUser:
    def __init__(self, id, username, first_name):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeCallback:
    def __init__(self, data, user):
        self.data = data
        self.from_user = user
        self.answer = AsyncMock()


async def _noop_threshold_callback(option_id):
    pass


async def test_handle_vote_toggle_registers_vote_and_updates_keyboard(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=10, username="alice", first_name="Alice"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 1

    fake_bot.edit_message_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Голос учтён!")


async def test_handle_vote_toggle_reaching_threshold_schedules_job(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(3):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"u{user_id}", first_name=f"U{user_id}"
            )

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=99, username="last", first_name="Last"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    assert scheduler.get_job(threshold_job_id(option.id)) is not None


async def test_handle_vote_toggle_dropping_below_threshold_sends_drop_message(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"u{user_id}", first_name=f"U{user_id}"
            )
        await repo.set_announced(session, option.id, True)

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=0, username="u0", first_name="U0"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100, text="За вариант «24.07» снова меньше 4х человек. Проголосуйте, а то игра отменится!"
    )
    async with session_maker() as session:
        assert await repo.is_announced(session, option.id) is False


async def test_handle_vote_toggle_handles_concurrent_double_tap_integrity_error(
    tmp_path, session_maker, monkeypatch
):
    """Simulates two concurrent CallbackQuery updates for the same user/button
    racing each other: both see 'no existing vote' before either commits, so
    the loser's insert violates the uq_vote_option_user unique constraint and
    repo.toggle_vote raises IntegrityError. The handler must not crash and
    must still answer the callback gracefully, without corrupting the count.
    """
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        # Simulate the "winner" of the race already having inserted its vote.
        await repo.toggle_vote(session, option.id, user_id=10, username="alice", first_name="Alice")

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=10, username="alice", first_name="Alice"))

    async def raise_integrity_error(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("UNIQUE constraint failed: votes.option_id, votes.user_id"))

    monkeypatch.setattr("bot.handlers.voting.repo.toggle_vote", raise_integrity_error)

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    callback.answer.assert_awaited_once()
    assert "секунд" in callback.answer.await_args.args[0]

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 1
