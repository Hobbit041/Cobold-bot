from bot import repo


async def test_pop_service_messages_returns_and_clears_recorded_ids(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=2)

    async with session_maker() as session:
        message_ids = await repo.pop_service_messages(session, chat_id=100, message_thread_id=None)

    assert sorted(message_ids) == [1, 2]

    async with session_maker() as session:
        assert await repo.pop_service_messages(session, chat_id=100, message_thread_id=None) == []


async def test_pop_service_messages_scoped_to_chat_and_thread(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)
        await repo.record_service_message(session, chat_id=100, message_thread_id=5, message_id=2)
        await repo.record_service_message(session, chat_id=200, message_thread_id=None, message_id=3)

    async with session_maker() as session:
        message_ids = await repo.pop_service_messages(session, chat_id=100, message_thread_id=None)

    assert message_ids == [1]
