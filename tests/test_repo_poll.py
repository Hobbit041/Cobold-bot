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


async def test_create_poll_accepts_option_with_no_date(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("Во что поиграть", None)]
        )

        options = await repo.get_poll_options(session, poll.id)
        assert options[0].date is None


async def test_set_poll_message_stores_message_id(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=555)

        stored = await repo.get_poll(session, poll.id)
        assert stored.message_id == 555


async def test_create_poll_defaults_message_thread_id_to_none(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )

        assert poll.message_thread_id is None


async def test_create_poll_stores_message_thread_id(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24))],
            message_thread_id=42,
        )

        assert poll.message_thread_id == 42


async def test_mark_poll_orphaned_sets_status(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.mark_poll_orphaned(session, poll.id)

        refreshed = await repo.get_poll(session, poll.id)
        assert refreshed.status == "orphaned"


async def test_delete_poll_removes_poll_and_all_related_data(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        options = await repo.get_poll_options(session, poll.id)
        kept_option, deleted_option = options
        await repo.toggle_vote(session, kept_option.id, user_id=5, username="alice", first_name="Alice")
        await repo.delete_option(session, deleted_option.id)

        poll_id = poll.id
        kept_option_id = kept_option.id
        deleted_option_id = deleted_option.id

        await repo.delete_poll(session, poll_id)

        assert await repo.get_poll(session, poll_id) is None
        assert await session.get(repo.Option, kept_option_id) is None
        assert await session.get(repo.Option, deleted_option_id) is None
        assert await session.get(repo.ThresholdState, kept_option_id) is None
        assert await session.get(repo.Reminder, kept_option_id) is None
        assert await repo.get_voters(session, kept_option_id) == []


async def test_delete_poll_on_nonexistent_poll_id_is_a_noop(session_maker):
    async with session_maker() as session:
        await repo.delete_poll(session, 999999)
