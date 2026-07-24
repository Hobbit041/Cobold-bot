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
