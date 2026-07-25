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
        threshold_debounce_seconds=900,
    )

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 1

    fake_bot.edit_message_text.assert_awaited_once()
    sent_kwargs = fake_bot.edit_message_text.await_args.kwargs
    assert sent_kwargs["chat_id"] == 100
    assert sent_kwargs["message_id"] == 42
    assert "1 🗳" in sent_kwargs["text"]
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
        threshold_debounce_seconds=900,
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
        threshold_debounce_seconds=900,
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text='За вариант "24.07 24 июля" снова меньше 4х человек. Проголосуйте, а то игра отменится!',
        message_thread_id=None,
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
        threshold_debounce_seconds=900,
    )

    callback.answer.assert_awaited_once()
    assert "секунд" in callback.answer.await_args.args[0]

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 1


async def test_handle_vote_toggle_survives_message_refresh_failure(tmp_path, session_maker):
    """If bot.edit_message_text raises (stale/deleted poll message, permission
    lost, transient API error), the vote is already committed and threshold
    bookkeeping must still run -- the tapper must still get a callback answer
    instead of a silently-spinning button.
    """
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
    fake_bot.edit_message_text.side_effect = Exception("message to edit not found")
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=99, username="last", first_name="Last"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=900,
    )

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 4

    assert scheduler.get_job(threshold_job_id(option.id)) is not None
    callback.answer.assert_awaited_once_with("Голос учтён!")


async def test_handle_vote_toggle_message_shows_voter_names(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        voted_option, other_option = options

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(
        data=f"vote:{voted_option.id}", user=FakeUser(id=10, username="alice", first_name="Alice")
    )

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=900,
    )

    sent_text = fake_bot.edit_message_text.await_args.kwargs["text"]
    assert sent_text == (
        "📅 Игра\n\n"
        "1. 24.07 (24 июля) — 1 🗳\n"
        "   @alice\n"
        "2. 25.07 (25 июля) — 0 🗳"
    )


async def test_handle_vote_toggle_uses_configured_debounce_seconds(tmp_path, session_maker):
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

    tz = ZoneInfo("Europe/Moscow")
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), tz)
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=99, username="last", first_name="Last"))

    before = dt.datetime.now(tz)
    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=10,
    )
    after = dt.datetime.now(tz)

    next_run_time = scheduler.get_job(threshold_job_id(option.id)).next_run_time
    assert before + dt.timedelta(seconds=10) <= next_run_time <= after + dt.timedelta(seconds=10)


async def test_handle_vote_toggle_does_not_reschedule_timer_on_extra_votes_past_threshold(
    tmp_path, session_maker
):
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

    tz = ZoneInfo("Europe/Moscow")
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), tz)
    fake_bot = AsyncMock()

    # First crossing (3 -> 4 votes already happened in setup via repo directly,
    # so this 5th vote is the one that pushes the handler's own decision logic
    # through SCHEDULE_TIMER for the first time within the handler itself).
    first_callback = FakeCallback(
        data=f"vote:{option.id}", user=FakeUser(id=10, username="ten", first_name="Ten")
    )
    await handle_vote_toggle(
        first_callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=900,
    )
    first_run_time = scheduler.get_job(threshold_job_id(option.id)).next_run_time
    assert first_run_time is not None

    # A 6th voter piles on while the timer is already counting down.
    second_callback = FakeCallback(
        data=f"vote:{option.id}", user=FakeUser(id=11, username="eleven", first_name="Eleven")
    )
    await handle_vote_toggle(
        second_callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=900,
    )
    second_run_time = scheduler.get_job(threshold_job_id(option.id)).next_run_time

    assert second_run_time == first_run_time


async def test_handle_vote_toggle_drop_message_uses_poll_message_thread_id(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24))],
            message_thread_id=42,
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
        threshold_debounce_seconds=900,
    )

    assert fake_bot.send_message.await_args.kwargs["message_thread_id"] == 42
