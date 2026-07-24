from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

from bot.handlers.admin_create import (
    CreatePollStates,
    finish_options,
    receive_option,
    receive_target_chat,
    receive_title,
    start_create_poll,
)
from bot.models import Poll


class FakeMessage:
    def __init__(self, text, user_id=1, forward_origin=None):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
        self.forward_origin = forward_origin
        self.forward_from_chat = None
        self.answer = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


async def test_start_create_poll_rejects_non_admin():
    message = FakeMessage("/newpoll", user_id=2)
    state = _state()

    await start_create_poll(message, state, admin_id=1)

    message.answer.assert_awaited_once_with("Эта команда доступна только администратору.")
    assert await state.get_state() is None


async def test_full_create_flow_persists_poll(session_maker):
    state = _state()

    admin_message = FakeMessage("/newpoll", user_id=1)
    await start_create_poll(admin_message, state, admin_id=1)
    assert await state.get_state() == CreatePollStates.waiting_title.state

    await receive_title(FakeMessage("Игра в апреле"), state)
    assert await state.get_state() == CreatePollStates.waiting_options.state

    await receive_option(FakeMessage("24.07 | 24.07.2026"), state)
    await receive_option(FakeMessage("25.07 | 25.07.2026"), state)
    data = await state.get_data()
    assert len(data["options"]) == 2

    await finish_options(FakeMessage("/done"), state)
    assert await state.get_state() == CreatePollStates.waiting_chat.state

    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 999})()

    await receive_target_chat(FakeMessage("-100123"), state, bot=fake_bot, session_maker=session_maker)

    fake_bot.send_message.assert_awaited_once()
    async with session_maker() as session:
        result = await session.execute(select(Poll))
        poll = result.scalar_one()
        assert poll.title == "Игра в апреле"
        assert poll.chat_id == -100123
        assert poll.message_id == 999
