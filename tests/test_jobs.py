import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import jobs, repo


class FakeBot:
    def __init__(self, id=1):
        self.id = id
        self.sent_messages = []
        self.deleted_messages = []

    async def send_message(self, chat_id, text, message_thread_id=None):
        self.sent_messages.append((chat_id, text, message_thread_id))

    async def delete_message(self, chat_id, message_id):
        self.deleted_messages.append((chat_id, message_id))


class FailingFakeBot:
    """Fails send_message for a specific chat_id, records everything else."""

    def __init__(self, fail_for_chat_id):
        self.fail_for_chat_id = fail_for_chat_id
        self.sent_messages = []

    async def send_message(self, chat_id, text, message_thread_id=None):
        if chat_id == self.fail_for_chat_id:
            raise RuntimeError("simulated Telegram API failure")
        self.sent_messages.append((chat_id, text, message_thread_id))


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

    assert fake_bot.sent_messages == [
        (555, '@admin, за вариант "24.07 24 июля" достаточно голосов для брони!', None)
    ]

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


async def test_threshold_check_callback_uses_poll_message_thread_id(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=555,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24))],
            message_thread_id=42,
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"user{user_id}", first_name=f"User{user_id}"
            )

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))
    await jobs.check_threshold(option.id)

    assert fake_bot.sent_messages[0][2] == 42


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
    chat_id, text, message_thread_id = fake_bot.sent_messages[0]
    assert chat_id == 777
    assert "@alice" in text
    assert message_thread_id is None

    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, option.id) is True


async def test_daily_reminder_callback_uses_poll_message_thread_id(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=777,
            title="Игра",
            options=[("Игра", tomorrow)],
            message_thread_id=42,
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")
        await repo.set_announced(session, option.id, True)

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=tz)
    await jobs.send_due_reminders()

    assert fake_bot.sent_messages[0][2] == 42


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


async def test_expire_dialog_clears_active_state_and_notifies(session_maker):
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=-100, user_id=1)
    state = FSMContext(storage=storage, key=key)
    await state.set_state("CreatePollStates:waiting_title")
    await state.update_data(last_bot_message_id=555)

    fake_bot = FakeBot(id=1)
    jobs.configure(
        fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"), storage=storage
    )

    await jobs.expire_dialog(-100, 1, 42)

    assert await state.get_state() is None
    assert fake_bot.deleted_messages == [(-100, 555)]
    assert len(fake_bot.sent_messages) == 1
    chat_id, text, message_thread_id = fake_bot.sent_messages[0]
    assert chat_id == -100
    assert message_thread_id == 42
    assert "отмен" in text.lower()


async def test_expire_dialog_noop_when_state_already_cleared(session_maker):
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=-100, user_id=1)

    fake_bot = FakeBot(id=1)
    jobs.configure(
        fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"), storage=storage
    )

    await jobs.expire_dialog(-100, 1, None)

    assert fake_bot.sent_messages == []
    assert fake_bot.deleted_messages == []


async def test_expire_dialog_is_module_level_and_pickleable_by_reference():
    assert jobs.expire_dialog.__qualname__ == "expire_dialog"


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
