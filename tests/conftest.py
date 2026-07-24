import datetime as dt

import pytest_asyncio

from bot import repo
from bot.db import create_engine_and_sessionmaker, init_db


@pytest_asyncio.fixture
async def session_maker(tmp_path):
    engine, maker = create_engine_and_sessionmaker(str(tmp_path / "test.sqlite3"))
    await init_db(engine)
    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def poll_and_option(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=1, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        options = await repo.get_poll_options(session, poll.id)
        return poll.id, options[0].id
