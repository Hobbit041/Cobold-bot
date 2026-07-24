import datetime as dt

from bot.models import Option, Poll


async def test_create_and_query_poll(session_maker):
    async with session_maker() as session:
        poll = Poll(chat_id=100, title="Игра в апреле", status="active")
        option = Option(text="24.07", date=dt.date(2026, 7, 24), position=0, poll=poll)
        session.add(poll)
        session.add(option)
        await session.commit()

        assert poll.id is not None
        assert option.poll_id == poll.id
