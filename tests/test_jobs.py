import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from bot import jobs, repo


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text):
        self.sent_messages.append((chat_id, text))


class FailingFakeBot:
    """Fails send_message for a specific chat_id, records everything else."""

    def __init__(self, fail_for_chat_id):
        self.fail_for_chat_id = fail_for_chat_id
        self.sent_messages = []

    async def send_message(self, chat_id, text):
        if chat_id == self.fail_for_chat_id:
            raise RuntimeError("simulated Telegram API failure")
        self.sent_messages.append((chat_id, text))


async def test_threshold_check_callback_announces_when_still_at_threshold(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"user{user_id}", first_name=f"User{user_id}"
            )

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))
    await jobs.check_threshold(option.id)

    assert fake_bot.sent_messages == [(555, "@admin, за вариант «24.07» проголосовало 4 человека!")]

    async with session_maker() as session:
        assert await repo.is_announced(session, option.id) is True


async def test_threshold_check_callback_skips_when_dropped_below(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="a", first_name="A")

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))
    await jobs.check_threshold(option.id)

    assert fake_bot.sent_messages == []


async def test_daily_reminder_callback_sends_and_marks_sent(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=777, title="Игра", options=[("Игра", tomorrow)])
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")
        await repo.set_announced(session, option.id, True)

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=tz)
    await jobs.send_due_reminders()

    assert len(fake_bot.sent_messages) == 1
    chat_id, text = fake_bot.sent_messages[0]
    assert chat_id == 777
    assert "@alice" in text

    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, option.id) is True


async def test_daily_reminder_callback_skips_not_announced(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=777, title="Игра", options=[("Игра", tomorrow)])
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=tz)
    await jobs.send_due_reminders()

    assert fake_bot.sent_messages == []


async def test_threshold_check_callback_skips_deleted_option(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"user{user_id}", first_name=f"User{user_id}"
            )
        await repo.delete_option(session, option.id)

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))
    await jobs.check_threshold(option.id)

    assert fake_bot.sent_messages == []


async def test_daily_reminder_callback_one_failed_send_does_not_block_others(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        failing_poll = await repo.create_poll(
            session, chat_id=888, title="Игра A", options=[("Игра A", tomorrow)]
        )
        failing_option = (await repo.get_poll_options(session, failing_poll.id))[0]
        await repo.toggle_vote(session, failing_option.id, user_id=1, username="alice", first_name="Alice")
        await repo.set_announced(session, failing_option.id, True)

        ok_poll = await repo.create_poll(session, chat_id=777, title="Игра B", options=[("Игра B", tomorrow)])
        ok_option = (await repo.get_poll_options(session, ok_poll.id))[0]
        await repo.toggle_vote(session, ok_option.id, user_id=2, username="bob", first_name="Bob")
        await repo.set_announced(session, ok_option.id, True)

    fake_bot = FailingFakeBot(fail_for_chat_id=888)
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=tz)
    await jobs.send_due_reminders()

    assert len(fake_bot.sent_messages) == 1
    assert fake_bot.sent_messages[0][0] == 777

    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, failing_option.id) is False
        assert await repo.is_reminder_sent(session, ok_option.id) is True


async def test_check_threshold_is_module_level_and_pickleable_by_reference():
    """APScheduler's SQLAlchemyJobStore pickles job callables by qualified name.

    A regression here (e.g. reverting to a closure returned by a factory) would
    make every job unschedulable against a persistent job store -- verify the
    reference is resolvable the same way apscheduler.util.obj_to_ref checks it,
    without depending on apscheduler internals directly.
    """
    assert jobs.check_threshold.__qualname__ == "check_threshold"
    assert jobs.send_due_reminders.__qualname__ == "send_due_reminders"


async def test_check_threshold_tracks_itself_in_in_flight_jobs_while_running(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))

    task = asyncio.ensure_future(jobs.check_threshold(option.id))
    await asyncio.sleep(0)
    was_tracked_while_running = task in jobs.in_flight_jobs
    await task

    assert was_tracked_while_running is True
    assert task not in jobs.in_flight_jobs
