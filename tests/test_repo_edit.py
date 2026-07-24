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
