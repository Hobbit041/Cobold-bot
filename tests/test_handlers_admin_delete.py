import datetime as dt
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.admin_delete import DeletePollStates, select_poll_to_delete, start_delete_poll


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(
        self, text, user_id=1, chat_type="private", chat_id=1, message_id=10, message_thread_id=None
    ):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
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


async def test_start_delete_poll_rejects_non_admin():
    message = FakeMessage("/deletepoll", user_id=2)
    state = _state()

    await start_delete_poll(message, state, admin_id=1, session_maker=None)

    message.answer.assert_awaited_once_with("Эта команда доступна только администратору.")
    assert await state.get_state() is None


async def test_start_delete_poll_reports_no_polls(session_maker):
    message = FakeMessage("/deletepoll", user_id=1)
    state = _state()

    await start_delete_poll(message, state, admin_id=1, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опросов нет.")
    assert await state.get_state() is None


async def test_start_delete_poll_lists_active_and_orphaned_polls(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Активный", options=[("24.07", dt.date(2026, 7, 24))]
        )
        orphaned_poll = await repo.create_poll(
            session, chat_id=100, title="Осиротевший", options=[("25.07", dt.date(2026, 7, 25))]
        )
        await repo.mark_poll_orphaned(session, orphaned_poll.id)

    message = FakeMessage("/deletepoll", user_id=1)
    state = _state()

    await start_delete_poll(message, state, admin_id=1, session_maker=session_maker)

    listed_text = message.answer.await_args.args[0]
    assert "Активный" in listed_text
    assert "Осиротевший" in listed_text
    assert "[опрос удалён, есть только в БД]" in listed_text
    data = await state.get_data()
    assert len(data["poll_ids"]) == 2


async def test_start_delete_poll_works_in_group_chat(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )

    message = FakeMessage("/deletepoll", user_id=1, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_delete_poll(message, state, admin_id=1, session_maker=session_maker)

    assert await state.get_state() == DeletePollStates.waiting_poll_selection.state
    message.delete.assert_awaited_once()


async def test_select_poll_to_delete_rejects_invalid_number(session_maker):
    state = _state()
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[1, 2, 3])

    message = FakeMessage("0")
    fake_bot = AsyncMock()

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Некорректный номер. Попробуйте снова.")
    assert await state.get_state() == DeletePollStates.waiting_poll_selection.state


async def test_select_poll_to_delete_removes_message_and_db_record(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        poll_id = poll.id

    state = _state()
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[poll_id])

    fake_bot = AsyncMock()
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    fake_bot.delete_message.assert_awaited_once_with(chat_id=100, message_id=42)
    message.answer.assert_awaited_once_with("Опрос удалён.")
    assert await state.get_state() is None

    async with session_maker() as session:
        assert await repo.get_poll(session, poll_id) is None


async def test_select_poll_to_delete_still_cleans_db_when_message_already_gone(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        poll_id = poll.id

    state = _state()
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[poll_id])

    fake_bot = AsyncMock()
    fake_bot.delete_message.side_effect = Exception("message to delete not found")
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опрос удалён.")
    async with session_maker() as session:
        assert await repo.get_poll(session, poll_id) is None
