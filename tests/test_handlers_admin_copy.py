import datetime as dt
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from bot import repo
from bot.handlers.admin_copy import CopyPollStates, select_poll_to_copy, start_copy_poll
from bot.models import Poll


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


async def test_start_copy_poll_rejects_non_admin():
    message = FakeMessage("/copypoll", user_id=2)
    state = _state()

    await start_copy_poll(message, state, admin_id=1, session_maker=None)

    message.answer.assert_awaited_once_with("Эта команда доступна только администратору.")
    assert await state.get_state() is None


async def test_start_copy_poll_rejects_private_chat():
    message = FakeMessage("/copypoll", user_id=1, chat_type="private")
    state = _state()

    await start_copy_poll(message, state, admin_id=1, session_maker=None)

    message.answer.assert_awaited_once_with(
        "Эта команда работает только в группе, в теме которую нужно скопировать опрос."
    )
    assert await state.get_state() is None


async def test_start_copy_poll_reports_no_active_polls(session_maker):
    message = FakeMessage("/copypoll", user_id=1, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_copy_poll(message, state, admin_id=1, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Активных опросов нет.")
    assert await state.get_state() is None


async def test_start_copy_poll_lists_active_polls_in_group(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Игра в апреле", options=[("24.07", dt.date(2026, 7, 24))]
        )

    message = FakeMessage(
        "/copypoll", user_id=1, chat_type="supergroup", chat_id=-500, message_thread_id=42
    )
    state = _state()

    await start_copy_poll(message, state, admin_id=1, session_maker=session_maker)

    assert await state.get_state() == CopyPollStates.waiting_poll_selection.state
    data = await state.get_data()
    assert data["target_chat_id"] == -500
    assert data["target_message_thread_id"] == 42
    listed_text = message.answer.await_args.args[0]
    assert "Игра в апреле" in listed_text


async def test_select_poll_to_copy_rejects_invalid_number(session_maker):
    state = _state()
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[1], target_chat_id=-500, target_message_thread_id=None)

    message = FakeMessage("banana", chat_type="supergroup", chat_id=-500)
    fake_bot = AsyncMock()

    await select_poll_to_copy(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Некорректный номер. Попробуйте снова.")
    assert await state.get_state() == CopyPollStates.waiting_poll_selection.state


async def test_select_poll_to_copy_creates_new_poll_without_votes_or_deleted_options(session_maker):
    async with session_maker() as session:
        source = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра в апреле",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        source_id = source.id
        source_options = await repo.get_poll_options(session, source_id)
        kept_option, dropped_option = source_options
        await repo.toggle_vote(session, kept_option.id, user_id=5, username="alice", first_name="Alice")
        await repo.delete_option(session, dropped_option.id)

    state = _state()
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[source_id], target_chat_id=-500, target_message_thread_id=42)

    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 999})()

    message = FakeMessage("1", chat_type="supergroup", chat_id=-500, message_thread_id=42)
    await select_poll_to_copy(message, state, bot=fake_bot, session_maker=session_maker)

    assert await state.get_state() is None
    fake_bot.send_message.assert_awaited_once()
    assert fake_bot.send_message.await_args.kwargs["chat_id"] == -500
    assert fake_bot.send_message.await_args.kwargs["message_thread_id"] == 42

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.id != source_id))
        new_poll = result.scalar_one()
        assert new_poll.title == "Игра в апреле"
        assert new_poll.chat_id == -500
        assert new_poll.message_thread_id == 42

        new_options = await repo.get_poll_options(session, new_poll.id)
        assert [o.text for o in new_options] == ["24.07"]
        assert await repo.get_vote_count(session, new_options[0].id) == 0
