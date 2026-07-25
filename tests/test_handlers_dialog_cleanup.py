from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.dialog_cleanup import cleanup_and_answer
from bot.scheduler import create_scheduler, dialog_timeout_job_id


class FakeChat:
    def __init__(self, id, type):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(self, chat_type="private", chat_id=1, message_id=10, user_id=1, message_thread_id=None):
        self.chat = FakeChat(chat_id, chat_type)
        self.message_id = message_id
        self.message_thread_id = message_thread_id
        self.from_user = type("U", (), {"id": user_id})()
        self.answer = AsyncMock()
        self.delete = AsyncMock()
        self.bot = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


def _scheduler(tmp_path):
    return create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))


async def test_private_chat_just_answers_without_deleting_anything():
    message = FakeMessage(chat_type="private")
    state = _state()

    result = await cleanup_and_answer(message, state, "hello")

    message.answer.assert_awaited_once_with("hello")
    message.delete.assert_not_awaited()
    message.bot.delete_message.assert_not_awaited()
    assert result is message.answer.return_value


async def test_group_chat_deletes_own_message_and_sends_reply():
    message = FakeMessage(chat_type="group", chat_id=-100, message_id=55)
    state = _state()
    sent = type("Sent", (), {"message_id": 999})()
    message.answer.return_value = sent

    await cleanup_and_answer(message, state, "hello")

    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with("hello")

    data = await state.get_data()
    assert data["last_bot_message_id"] == 999


async def test_group_chat_deletes_previous_bot_prompt_before_sending_next():
    message = FakeMessage(chat_type="supergroup", chat_id=-100, message_id=56)
    state = _state()
    await state.update_data(last_bot_message_id=42)
    sent = type("Sent", (), {"message_id": 1000})()
    message.answer.return_value = sent

    await cleanup_and_answer(message, state, "next step")

    message.bot.delete_message.assert_awaited_once_with(chat_id=-100, message_id=42)

    data = await state.get_data()
    assert data["last_bot_message_id"] == 1000


async def test_group_chat_survives_delete_failures():
    message = FakeMessage(chat_type="group", chat_id=-100, message_id=57)
    message.delete.side_effect = Exception("message can't be deleted")
    state = _state()
    await state.update_data(last_bot_message_id=42)
    message.bot.delete_message.side_effect = Exception("message to delete not found")
    sent = type("Sent", (), {"message_id": 1001})()
    message.answer.return_value = sent

    result = await cleanup_and_answer(message, state, "still works")

    message.answer.assert_awaited_once_with("still works")
    assert result is sent


async def test_group_chat_schedules_dialog_timeout_when_state_active(tmp_path):
    message = FakeMessage(chat_type="group", chat_id=-100, message_id=60, user_id=7, message_thread_id=42)
    state = _state()
    await state.set_state("CreatePollStates:waiting_title")
    scheduler = _scheduler(tmp_path)

    await cleanup_and_answer(message, state, "hello", scheduler=scheduler)

    job = scheduler.get_job(dialog_timeout_job_id(-100, 7))
    assert job is not None
    assert job.args == (-100, 7, 42)


def _noop_dialog_timeout(chat_id, user_id, message_thread_id):
    pass


async def test_group_chat_cancels_dialog_timeout_when_state_cleared(tmp_path):
    message = FakeMessage(chat_type="group", chat_id=-100, message_id=61, user_id=7)
    state = _state()
    scheduler = _scheduler(tmp_path)
    # Simulate a timeout already pending from a previous step in this dialog.
    from bot.scheduler import schedule_dialog_timeout

    schedule_dialog_timeout(scheduler, -100, 7, None, callback=_noop_dialog_timeout)

    await cleanup_and_answer(message, state, "done", scheduler=scheduler)

    assert scheduler.get_job(dialog_timeout_job_id(-100, 7)) is None


async def test_group_chat_without_scheduler_does_not_error(tmp_path):
    message = FakeMessage(chat_type="group", chat_id=-100, message_id=62)
    state = _state()
    await state.set_state("CreatePollStates:waiting_title")

    result = await cleanup_and_answer(message, state, "hello")

    assert result is message.answer.return_value
