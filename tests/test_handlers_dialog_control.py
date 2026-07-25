from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.admin_create import CreatePollStates
from bot.handlers.dialog_control import cancel_dialog
from bot.scheduler import create_scheduler, dialog_timeout_job_id, schedule_dialog_timeout


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(self, user_id=1, chat_type="private", chat_id=1, message_id=10):
        self.text = "/cancel"
        self.from_user = type("U", (), {"id": user_id})()
        self.chat = FakeChat(chat_id, chat_type)
        self.message_id = message_id
        self.message_thread_id = None
        self.answer = AsyncMock()
        self.delete = AsyncMock()
        self.bot = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


def _noop_dialog_timeout(chat_id, user_id, message_thread_id):
    pass


async def test_cancel_rejects_non_admin():
    message = FakeMessage(user_id=2)
    state = _state()

    await cancel_dialog(message, state, admin_id=1)

    message.answer.assert_awaited_once_with("Эта команда доступна только администратору.")


async def test_cancel_with_no_active_dialog_says_nothing_to_cancel():
    message = FakeMessage(user_id=1)
    state = _state()

    await cancel_dialog(message, state, admin_id=1)

    message.answer.assert_awaited_once_with("Нечего отменять.")


async def test_cancel_clears_active_create_poll_dialog():
    message = FakeMessage(user_id=1)
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[{"text": "24.07", "date": "2026-07-24"}])

    await cancel_dialog(message, state, admin_id=1)

    assert await state.get_state() is None
    message.answer.assert_awaited_once_with("Действие отменено.")


async def test_cancel_in_group_deletes_messages_and_cancels_pending_timeout(tmp_path):
    message = FakeMessage(user_id=1, chat_type="group", chat_id=-500, message_id=7)
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    schedule_dialog_timeout(scheduler, -500, 1, None, callback=_noop_dialog_timeout)

    await cancel_dialog(message, state, admin_id=1, scheduler=scheduler)

    message.delete.assert_awaited_once()
    assert await state.get_state() is None
    assert scheduler.get_job(dialog_timeout_job_id(-500, 1)) is None
