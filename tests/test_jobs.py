import datetime as dt
from zoneinfo import ZoneInfo

from bot import jobs, repo


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text):
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
    callback = jobs.make_threshold_check_callback(fake_bot, session_maker, admin_mention="@admin")
    await callback(option.id)

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
    callback = jobs.make_threshold_check_callback(fake_bot, session_maker, admin_mention="@admin")
    await callback(option.id)

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
    callback = jobs.make_daily_reminder_callback(fake_bot, session_maker, tz)
    await callback()

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
    callback = jobs.make_daily_reminder_callback(fake_bot, session_maker, tz)
    await callback()

    assert fake_bot.sent_messages == []
