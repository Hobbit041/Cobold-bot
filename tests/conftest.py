import pytest_asyncio

from bot.db import create_engine_and_sessionmaker, init_db


@pytest_asyncio.fixture
async def session_maker(tmp_path):
    engine, maker = create_engine_and_sessionmaker(str(tmp_path / "test.sqlite3"))
    await init_db(engine)
    yield maker
    await engine.dispose()
