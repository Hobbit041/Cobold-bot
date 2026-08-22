import datetime as dt
from zoneinfo import ZoneInfo

from bot import repo


async def test_toggle_vote_adds_then_removes(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        voted_now, count = await repo.toggle_vote(
            session, option_id, user_id=10, username="alice", first_name="Alice"
        )
        assert (voted_now, count) == (True, 1)

        voted_now, count = await repo.toggle_vote(
            session, option_id, user_id=10, username="alice", first_name="Alice"
        )
        assert (voted_now, count) == (False, 0)


async def test_toggle_vote_counts_multiple_users(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        await repo.toggle_vote(session, option_id, user_id=10, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_id, user_id=11, username=None, first_name="Bob")

        voters = await repo.get_voters(session, option_id)
        assert {v.user_id for v in voters} == {10, 11}
        assert await repo.get_vote_count(session, option_id) == 2


async def test_get_votes_by_user_orders_by_date_and_excludes_dateless_and_other_users(session_maker):
    async with session_maker() as session:
        poll_a = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра А",
            options=[("Позже", dt.date(2026, 9, 1)), ("Без даты", None)],
        )
        poll_b = await repo.create_poll(
            session, chat_id=200, title="Игра Б", options=[("Раньше", dt.date(2026, 8, 1))]
        )
        options_a = await repo.get_poll_options(session, poll_a.id)
        options_b = await repo.get_poll_options(session, poll_b.id)
        dated_a, dateless_a = options_a[0], options_a[1]
        dated_b = options_b[0]

        await repo.toggle_vote(session, dated_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dateless_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dated_b.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dated_b.id, user_id=2, username="bob", first_name="Bob")

        rows = await repo.get_votes_by_user(session, user_id=1)

    assert [(poll.id, option.id) for poll, option in rows] == [
        (poll_b.id, dated_b.id),
        (poll_a.id, dated_a.id),
    ]


async def test_get_votes_by_user_excludes_deleted_option(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")
        option.is_deleted = True
        await session.commit()

        rows = await repo.get_votes_by_user(session, user_id=1)

    assert rows == []


async def test_get_votes_by_user_with_no_votes_returns_empty_list(session_maker):
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user_id=999)

    assert rows == []


async def test_get_votes_by_user_on_or_after_includes_today_and_future_excludes_past(session_maker):
    today = dt.datetime.now(ZoneInfo("Europe/Moscow")).date()
    async with session_maker() as session:
        poll_today = await repo.create_poll(
            session, chat_id=100, title="Сегодня", options=[("Сегодня", today)]
        )
        poll_future = await repo.create_poll(
            session, chat_id=100, title="Будущее", options=[("Будущее", today + dt.timedelta(days=1))]
        )
        poll_past = await repo.create_poll(
            session, chat_id=100, title="Прошлое", options=[("Прошлое", today - dt.timedelta(days=1))]
        )
        option_today = (await repo.get_poll_options(session, poll_today.id))[0]
        option_future = (await repo.get_poll_options(session, poll_future.id))[0]
        option_past = (await repo.get_poll_options(session, poll_past.id))[0]
        await repo.toggle_vote(session, option_today.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_future.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_past.id, user_id=1, username="alice", first_name="Alice")

        rows = await repo.get_votes_by_user(session, user_id=1, on_or_after=today)

    assert [option.id for _, option in rows] == [option_today.id, option_future.id]


async def test_get_votes_by_user_before_includes_past_excludes_today_and_future(session_maker):
    today = dt.datetime.now(ZoneInfo("Europe/Moscow")).date()
    async with session_maker() as session:
        poll_today = await repo.create_poll(
            session, chat_id=100, title="Сегодня", options=[("Сегодня", today)]
        )
        poll_future = await repo.create_poll(
            session, chat_id=100, title="Будущее", options=[("Будущее", today + dt.timedelta(days=1))]
        )
        poll_past = await repo.create_poll(
            session, chat_id=100, title="Прошлое", options=[("Прошлое", today - dt.timedelta(days=1))]
        )
        option_today = (await repo.get_poll_options(session, poll_today.id))[0]
        option_future = (await repo.get_poll_options(session, poll_future.id))[0]
        option_past = (await repo.get_poll_options(session, poll_past.id))[0]
        await repo.toggle_vote(session, option_today.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_future.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_past.id, user_id=1, username="alice", first_name="Alice")

        rows = await repo.get_votes_by_user(session, user_id=1, before=today)

    assert [option.id for _, option in rows] == [option_past.id]
