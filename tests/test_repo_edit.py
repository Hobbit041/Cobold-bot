import datetime as dt

from bot import repo
from bot.models import Reminder, ThresholdState


async def test_edit_option_text(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        updated = await repo.edit_option_text(session, option_id, "25.07 вместо 24.07")
        assert updated.text == "25.07 вместо 24.07"


async def test_edit_option_date(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        updated = await repo.edit_option_date(session, option_id, dt.date(2026, 8, 1))
        assert updated.date == dt.date(2026, 8, 1)


async def test_edit_poll_title(session_maker, poll_and_option):
    poll_id, _ = poll_and_option
    async with session_maker() as session:
        updated = await repo.edit_poll_title(session, poll_id, "Новая игра")
        assert updated.title == "Новая игра"

    async with session_maker() as session:
        assert (await repo.get_poll(session, poll_id)).title == "Новая игра"


async def test_delete_option_removes_votes_and_marks_deleted(session_maker, poll_and_option):
    poll_id, option_id = poll_and_option
    async with session_maker() as session:
        await repo.toggle_vote(session, option_id, user_id=10, username="alice", first_name="Alice")
        await repo.delete_option(session, option_id)

        remaining_options = await repo.get_poll_options(session, poll_id)
        assert remaining_options == []
        assert await repo.get_vote_count(session, option_id) == 0
        assert await session.get(ThresholdState, option_id) is None
        assert await session.get(Reminder, option_id) is None


async def test_add_option_appends_after_existing_options(session_maker, poll_and_option):
    poll_id, _ = poll_and_option
    async with session_maker() as session:
        new_option = await repo.add_option(session, poll_id, "25.07", dt.date(2026, 7, 25))

        options = await repo.get_poll_options(session, poll_id)
        assert [o.text for o in options] == ["24.07", "25.07"]
        assert new_option.position > options[0].position


async def test_add_option_creates_threshold_and_reminder_rows(session_maker, poll_and_option):
    poll_id, _ = poll_and_option
    async with session_maker() as session:
        new_option = await repo.add_option(session, poll_id, "25.07", dt.date(2026, 7, 25))

        assert await session.get(ThresholdState, new_option.id) is not None
        assert await session.get(Reminder, new_option.id) is not None
        assert await repo.get_vote_count(session, new_option.id) == 0


async def test_add_option_to_poll_with_no_existing_options(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=1, title="Игра", options=[])
        new_option = await repo.add_option(session, poll.id, "24.07", dt.date(2026, 7, 24))

        assert new_option.position == 0


async def test_add_option_without_date(session_maker, poll_and_option):
    poll_id, _ = poll_and_option
    async with session_maker() as session:
        new_option = await repo.add_option(session, poll_id, "Во что поиграть", None)

        assert new_option.date is None


async def test_reorder_options_updates_position_order(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=1,
            title="Игра",
            options=[("A", None), ("B", None), ("C", None), ("D", None)],
        )
        options = await repo.get_poll_options(session, poll.id)
        ids = [o.id for o in options]

    async with session_maker() as session:
        await repo.reorder_options(session, [ids[2], ids[0], ids[3], ids[1]])

    async with session_maker() as session:
        reordered = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in reordered] == ["C", "A", "D", "B"]
