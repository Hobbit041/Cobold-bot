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


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(
        self,
        text,
        user_id=1,
        forward_origin=None,
        chat_type="private",
        chat_id=1,
        message_id=10,
        message_thread_id=None,
    ):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
        self.forward_origin = forward_origin
        self.forward_from_chat = None
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

    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 999})()

    await finish_options(FakeMessage("/done"), state, bot=fake_bot, session_maker=session_maker)
    assert await state.get_state() == CreatePollStates.waiting_chat.state

    await receive_target_chat(FakeMessage("-100123"), state, bot=fake_bot, session_maker=session_maker)

    fake_bot.send_message.assert_awaited_once()
    async with session_maker() as session:
        result = await session.execute(select(Poll))
        poll = result.scalar_one()
        assert poll.title == "Игра в апреле"
        assert poll.chat_id == -100123
        assert poll.message_id == 999


async def test_receive_option_accepts_slash_separator():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("24.07 / 24.07.2026")
    await receive_option(message, state)

    data = await state.get_data()
    assert data["options"] == [{"text": "24.07", "date": "2026-07-24"}]
    message.answer.assert_awaited_once()
    assert "Добавлено" in message.answer.await_args.args[0]


async def test_receive_option_accepts_backslash_separator():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("24.07 \\ 24.07.2026")
    await receive_option(message, state)

    data = await state.get_data()
    assert data["options"] == [{"text": "24.07", "date": "2026-07-24"}]


async def test_receive_option_still_accepts_pipe_separator():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("24.07 | 24.07.2026")
    await receive_option(message, state)

    data = await state.get_data()
    assert data["options"] == [{"text": "24.07", "date": "2026-07-24"}]


async def test_receive_option_rejects_line_with_no_separator():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("24.07 24.07.2026")
    await receive_option(message, state)

    message.answer.assert_awaited_once()
    data = await state.get_data()
    assert data["options"] == []


async def test_receive_target_chat_cleans_up_when_send_fails(session_maker):
    state = _state()

    admin_message = FakeMessage("/newpoll", user_id=1)
    await start_create_poll(admin_message, state, admin_id=1)
    await receive_title(FakeMessage("Игра в апреле"), state)
    await receive_option(FakeMessage("24.07 | 24.07.2026"), state)

    fake_bot = AsyncMock()
    fake_bot.send_message.side_effect = Exception("chat not found")
    await finish_options(FakeMessage("/done"), state, bot=fake_bot, session_maker=session_maker)

    target_message = FakeMessage("-100123")
    await receive_target_chat(target_message, state, bot=fake_bot, session_maker=session_maker)

    target_message.answer.assert_awaited_once()
    error_text = target_message.answer.await_args.args[0]
    assert "не удалось" in error_text.lower() or "не уда" in error_text.lower()

    async with session_maker() as session:
        result = await session.execute(select(Poll))
        assert result.scalars().all() == []

    assert await state.get_state() == CreatePollStates.waiting_chat.state


async def test_newpoll_started_in_group_publishes_directly_without_asking_for_chat(session_maker):
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 777})()

    admin_message = FakeMessage("/newpoll", user_id=1, chat_type="supergroup", chat_id=-500)
    await start_create_poll(admin_message, state, admin_id=1)
    assert await state.get_state() == CreatePollStates.waiting_title.state

    await receive_title(
        FakeMessage("Игра", chat_type="supergroup", chat_id=-500), state
    )
    await receive_option(
        FakeMessage("24.07 | 24.07.2026", chat_type="supergroup", chat_id=-500), state
    )

    done_message = FakeMessage("/done", chat_type="supergroup", chat_id=-500)
    await finish_options(done_message, state, bot=fake_bot, session_maker=session_maker)

    # No "waiting_chat" step -- the poll is created and published immediately.
    assert await state.get_state() is None
    fake_bot.send_message.assert_awaited_once()
    assert fake_bot.send_message.await_args.kwargs["chat_id"] == -500

    async with session_maker() as session:
        result = await session.execute(select(Poll))
        poll = result.scalar_one()
        assert poll.chat_id == -500
        assert poll.message_id == 777


async def test_newpoll_started_in_forum_topic_publishes_with_message_thread_id(session_maker):
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 778})()

    admin_message = FakeMessage(
        "/newpoll", user_id=1, chat_type="supergroup", chat_id=-500, message_thread_id=42
    )
    await start_create_poll(admin_message, state, admin_id=1)
    await receive_title(
        FakeMessage("Игра", chat_type="supergroup", chat_id=-500, message_thread_id=42), state
    )
    await receive_option(
        FakeMessage("24.07 | 24.07.2026", chat_type="supergroup", chat_id=-500, message_thread_id=42),
        state,
    )

    done_message = FakeMessage("/done", chat_type="supergroup", chat_id=-500, message_thread_id=42)
    await finish_options(done_message, state, bot=fake_bot, session_maker=session_maker)

    assert fake_bot.send_message.await_args.kwargs["message_thread_id"] == 42

    async with session_maker() as session:
        result = await session.execute(select(Poll))
        poll = result.scalar_one()
        assert poll.message_thread_id == 42


async def test_newpoll_started_in_private_chat_still_asks_for_target_chat(session_maker):
    state = _state()

    admin_message = FakeMessage("/newpoll", user_id=1, chat_type="private")
    await start_create_poll(admin_message, state, admin_id=1)
    await receive_title(FakeMessage("Игра", chat_type="private"), state)
    await receive_option(FakeMessage("24.07 | 24.07.2026", chat_type="private"), state)

    fake_bot = AsyncMock()
    await finish_options(
        FakeMessage("/done", chat_type="private"), state, bot=fake_bot, session_maker=session_maker
    )

    assert await state.get_state() == CreatePollStates.waiting_chat.state
    fake_bot.send_message.assert_not_awaited()


async def test_newpoll_started_in_group_deletes_admin_messages_and_previous_prompts(session_maker):
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 779})()

    start_message = FakeMessage(
        "/newpoll", user_id=1, chat_type="group", chat_id=-501, message_id=1
    )
    await start_create_poll(start_message, state, admin_id=1)
    start_message.delete.assert_awaited_once()

    title_message = FakeMessage("Игра", chat_type="group", chat_id=-501, message_id=2)
    await receive_title(title_message, state)
    title_message.delete.assert_awaited_once()
    # Deletes the bot's previous prompt ("Введите название опроса:") too.
    title_message.bot.delete_message.assert_awaited_once()
