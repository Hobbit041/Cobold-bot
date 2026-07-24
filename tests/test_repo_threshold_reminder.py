import datetime as dt

from bot import repo


async def test_announced_defaults_false_and_can_be_set(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        assert await repo.is_announced(session, option_id) is False

        await repo.set_announced(session, option_id, True)
        assert await repo.is_announced(session, option_id) is True


async def test_reminder_sent_defaults_false_and_can_be_set(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, option_id) is False

        await repo.set_reminder_sent(session, option_id, True)
        assert await repo.is_reminder_sent(session, option_id) is True


async def test_get_options_due_for_reminder_filters_correctly(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=1,
            title="Игра",
            options=[
                ("Вариант A", dt.date(2026, 7, 25)),
                ("Вариант B", dt.date(2026, 7, 25)),
                ("Вариант C", dt.date(2026, 7, 26)),
            ],
        )
        options = await repo.get_poll_options(session, poll.id)
        option_a, option_b, option_c = options

        await repo.set_announced(session, option_a.id, True)
        await repo.set_announced(session, option_b.id, True)
        await repo.set_reminder_sent(session, option_b.id, True)
        await repo.set_announced(session, option_c.id, True)

        due = await repo.get_options_due_for_reminder(session, dt.date(2026, 7, 25))

        assert [o.id for o in due] == [option_a.id]
