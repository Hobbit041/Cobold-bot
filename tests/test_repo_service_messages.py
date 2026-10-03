from bot import repo


async def test_get_service_messages_returns_recorded_ids_oldest_first(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=2)
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == [2, 1]


async def test_get_service_messages_scoped_to_chat_and_thread(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)
        await repo.record_service_message(session, chat_id=100, message_thread_id=5, message_id=2)
        await repo.record_service_message(session, chat_id=200, message_thread_id=None, message_id=3)

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == [1]


async def test_forget_service_messages_drops_only_the_given_ids(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=2)
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=3)

    async with session_maker() as session:
        await repo.forget_service_messages(
            session, chat_id=100, message_thread_id=None, message_ids=[1, 3]
        )

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == [2]


async def test_forget_service_messages_is_scoped_to_chat_and_thread(session_maker):
    """Same message_id in another chat/thread must survive -- ids are per-chat."""
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=7)
        await repo.record_service_message(session, chat_id=100, message_thread_id=5, message_id=7)
        await repo.record_service_message(session, chat_id=200, message_thread_id=None, message_id=7)

    async with session_maker() as session:
        await repo.forget_service_messages(
            session, chat_id=100, message_thread_id=None, message_ids=[7]
        )

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == []
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=5) == [7]
        assert await repo.get_service_messages(session, chat_id=200, message_thread_id=None) == [7]


async def test_forget_service_messages_with_no_ids_is_a_no_op(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=100, message_thread_id=None, message_id=1)

    async with session_maker() as session:
        await repo.forget_service_messages(
            session, chat_id=100, message_thread_id=None, message_ids=[]
        )

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == [1]


async def test_forget_service_messages_handles_more_ids_than_sqlite_takes_at_once(session_maker):
    """More ids than one statement can bind -- must still clear all of them."""
    total = 1200
    async with session_maker() as session:
        for message_id in range(1, total + 1):
            await repo.record_service_message(
                session, chat_id=100, message_thread_id=None, message_id=message_id
            )

    async with session_maker() as session:
        await repo.forget_service_messages(
            session, chat_id=100, message_thread_id=None, message_ids=list(range(1, total + 1))
        )

    async with session_maker() as session:
        assert await repo.get_service_messages(session, chat_id=100, message_thread_id=None) == []
