import datetime as dt

from bot import repo


async def test_create_poll_creates_options_with_state(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )

        options = await repo.get_poll_options(session, poll.id)

        assert [o.text for o in options] == ["24.07", "25.07"]
        assert options[0].position == 0
        assert options[1].position == 1


async def test_set_poll_message_stores_message_id(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=555)

        stored = await repo.get_poll(session, poll.id)
        assert stored.message_id == 555
