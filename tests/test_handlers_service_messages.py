from unittest.mock import AsyncMock

from aiogram.enums import ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.service_messages import (
    TRACKED_CONTENT_TYPES,
    handle_clear,
    track_service_message,
)


class FakeChat:
    def __init__(self, id=-500, type="supergroup"):
        self.id = id
        self.type = type


class FakeChatMember:
    def __init__(self, status):
        self.status = status


class FakeMessage:
    def __init__(
        self,
        user_id=1,
        chat_type="supergroup",
        chat_id=-500,
        message_id=10,
        message_thread_id=None,
    ):
        self.from_user = type("U", (), {"id": user_id})() if user_id is not None else None
        self.chat = FakeChat(chat_id, chat_type)
        self.message_id = message_id
        self.message_thread_id = message_thread_id
        self.answer = AsyncMock()
        self.delete = AsyncMock()
        self.bot = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


def _admin_bot():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    return bot


def test_tracked_content_types_covers_join_leave_and_pin_but_not_payments():
    assert ContentType.NEW_CHAT_MEMBERS in TRACKED_CONTENT_TYPES
    assert ContentType.LEFT_CHAT_MEMBER in TRACKED_CONTENT_TYPES
    assert ContentType.PINNED_MESSAGE in TRACKED_CONTENT_TYPES
    assert ContentType.SUCCESSFUL_PAYMENT not in TRACKED_CONTENT_TYPES
    assert ContentType.TEXT not in TRACKED_CONTENT_TYPES


async def test_track_service_message_records_it(session_maker):
    message = FakeMessage(chat_id=-500, message_thread_id=7, message_id=42)

    await track_service_message(message, session_maker=session_maker)

    async with session_maker() as session:
        message_ids = await repo.pop_service_messages(session, chat_id=-500, message_thread_id=7)
    assert message_ids == [42]


async def test_handle_clear_in_private_chat_replies_and_deletes_nothing(session_maker):
    message = FakeMessage(chat_type="private", chat_id=1)
    state = _state()
    fake_bot = AsyncMock()

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once()
    message.delete.assert_not_awaited()
    fake_bot.get_chat_member.assert_not_awaited()


async def test_handle_clear_rejects_non_admin(session_maker):
    message = FakeMessage(user_id=2)
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Эта команда доступна только администраторам этого чата.")
    message.delete.assert_awaited_once()
    fake_bot.delete_message.assert_not_awaited()


async def test_handle_clear_rejects_anonymous_sender(session_maker):
    message = FakeMessage(user_id=None)
    state = _state()
    fake_bot = AsyncMock()

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Эта команда доступна только администраторам этого чата.")
    fake_bot.get_chat_member.assert_not_awaited()
    fake_bot.delete_message.assert_not_awaited()


async def test_handle_clear_reports_nothing_to_clear(session_maker):
    message = FakeMessage()
    state = _state()

    await handle_clear(message, state, bot=_admin_bot(), session_maker=session_maker)

    message.answer.assert_awaited_once_with("Нечего удалять.")
    message.delete.assert_awaited_once()


async def test_handle_clear_deletes_tracked_messages_for_its_own_chat_and_thread(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=-500, message_thread_id=None, message_id=101)
        await repo.record_service_message(session, chat_id=-500, message_thread_id=None, message_id=102)
        # Different thread and different chat -- must not be touched.
        await repo.record_service_message(session, chat_id=-500, message_thread_id=9, message_id=999)
        await repo.record_service_message(session, chat_id=-999, message_thread_id=None, message_id=888)

    message = FakeMessage(chat_id=-500, message_thread_id=None)
    state = _state()
    fake_bot = _admin_bot()

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    assert fake_bot.delete_message.await_count == 2
    fake_bot.delete_message.assert_any_await(chat_id=-500, message_id=101)
    fake_bot.delete_message.assert_any_await(chat_id=-500, message_id=102)
    message.answer.assert_awaited_once_with("Удалено 2 сообщения.")
    message.delete.assert_awaited_once()

    async with session_maker() as session:
        remaining_thread_9 = await repo.pop_service_messages(session, chat_id=-500, message_thread_id=9)
        remaining_other_chat = await repo.pop_service_messages(session, chat_id=-999, message_thread_id=None)
    assert remaining_thread_9 == [999]
    assert remaining_other_chat == [888]


async def test_handle_clear_scopes_to_the_topic_it_was_run_in(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=-500, message_thread_id=9, message_id=201)
        # Different thread in the same chat -- must not be touched.
        await repo.record_service_message(session, chat_id=-500, message_thread_id=None, message_id=202)

    message = FakeMessage(chat_id=-500, message_thread_id=9)
    state = _state()
    fake_bot = _admin_bot()

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    fake_bot.delete_message.assert_awaited_once_with(chat_id=-500, message_id=201)
    message.answer.assert_awaited_once_with("Удалено 1 сообщение.")

    async with session_maker() as session:
        remaining_general = await repo.pop_service_messages(session, chat_id=-500, message_thread_id=None)
    assert remaining_general == [202]


async def test_handle_clear_still_reports_success_when_a_message_is_already_gone(session_maker):
    async with session_maker() as session:
        await repo.record_service_message(session, chat_id=-500, message_thread_id=None, message_id=101)

    message = FakeMessage(chat_id=-500, message_thread_id=None)
    state = _state()
    fake_bot = _admin_bot()
    fake_bot.delete_message.side_effect = Exception("message to delete not found")

    await handle_clear(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Нечего удалять.")
