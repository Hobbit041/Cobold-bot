import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.formatting import TOO_OLD_TO_DELETE
from bot.handlers.admin_delete import DeletePollStates, select_poll_to_delete, start_delete_poll
from bot.scheduler import create_scheduler, message_deletion_job_id


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=f"Bad Request: {message}")


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeChatMember:
    def __init__(self, status):
        self.status = status


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


class FakeResolvedChat:
    def __init__(self, username=None):
        self.username = username


def _admin_bot(chat_username=None):
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    # Without this, get_chat returns an AsyncMock whose .username is a truthy
    # Mock, and the poll listing builds links out of its repr.
    bot.get_chat.return_value = FakeResolvedChat(username=chat_username)
    return bot


async def test_start_delete_poll_reports_no_polls(session_maker):
    message = FakeMessage("/deletepoll", user_id=1)
    state = _state()

    await start_delete_poll(message, state, bot=AsyncMock(), session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опросов нет.")
    assert await state.get_state() is None


async def test_start_delete_poll_hides_polls_from_chats_user_does_not_administer(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )

    message = FakeMessage("/deletepoll", user_id=2)
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")

    await start_delete_poll(message, state, bot=fake_bot, session_maker=session_maker)

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

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    listed_text = message.answer.await_args.args[0]
    assert "Активный" in listed_text
    assert "Осиротевший" in listed_text
    assert "[опрос удалён, есть только в БД]" in listed_text
    data = await state.get_data()
    assert len(data["poll_ids"]) == 2


async def test_start_delete_poll_only_lists_polls_from_administered_chats(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Моя группа", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.create_poll(
            session, chat_id=200, title="Чужая группа", options=[("25.07", dt.date(2026, 7, 25))]
        )

    message = FakeMessage("/deletepoll", user_id=1)
    state = _state()
    fake_bot = AsyncMock()

    async def _get_chat_member(chat_id, user_id):
        statuses = {100: "administrator", 200: "member"}
        return FakeChatMember(status=statuses[chat_id])

    fake_bot.get_chat_member.side_effect = _get_chat_member

    await start_delete_poll(message, state, bot=fake_bot, session_maker=session_maker)

    listed_text = message.answer.await_args.args[0]
    assert "Моя группа" in listed_text
    assert "Чужая группа" not in listed_text
    data = await state.get_data()
    assert len(data["poll_ids"]) == 1


async def test_start_delete_poll_works_in_group_chat(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )

    message = FakeMessage("/deletepoll", user_id=1, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

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
    fake_bot.delete_message.side_effect = _bad_request("message to delete not found")
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опрос удалён.")
    async with session_maker() as session:
        assert await repo.get_poll(session, poll_id) is None


async def _delete_poll_with_failing_message_delete(session_maker, error):
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
    fake_bot.delete_message.side_effect = error
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    async with session_maker() as session:
        assert await repo.get_poll(session, poll_id) is None
    return message


async def test_select_poll_to_delete_says_so_when_the_message_is_too_old_to_delete(session_maker):
    """The DB row still goes, but don't claim the chat message went with it."""
    message = await _delete_poll_with_failing_message_delete(
        session_maker, _bad_request("message can't be deleted for everyone")
    )

    message.answer.assert_awaited_once_with(
        "Опрос удалён из бота, но его сообщение осталось в чате: "
        f"{TOO_OLD_TO_DELETE} Удалите его вручную."
    )


async def test_select_poll_to_delete_says_so_when_deleting_the_message_fails(session_maker):
    message = await _delete_poll_with_failing_message_delete(
        session_maker, TelegramNetworkError(method=None, message="timed out")
    )

    message.answer.assert_awaited_once_with(
        "Опрос удалён из бота, но убрать его сообщение из чата не получилось — "
        "удалите его вручную."
    )


async def test_select_poll_to_delete_in_group_cleans_prompt_and_schedules_confirmation(
    session_maker, tmp_path
):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        poll_id = poll.id

    state = _state()
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[poll_id], last_bot_message_id=777)

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    message = FakeMessage("1", chat_type="supergroup", chat_id=-500, message_id=88)
    sent = type("Sent", (), {"message_id": 900})()
    message.answer.return_value = sent

    await select_poll_to_delete(
        message, state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )

    message.bot.delete_message.assert_awaited_once_with(chat_id=-500, message_id=777)
    message.answer.assert_awaited_once_with("Опрос удалён.")
    assert await state.get_state() is None
    assert scheduler.get_job(message_deletion_job_id(-500, 900)) is not None


async def test_select_poll_to_delete_when_poll_already_gone(session_maker):
    state = _state()
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[999999])

    fake_bot = AsyncMock()
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опрос уже удалён.")
    fake_bot.delete_message.assert_not_awaited()
    assert await state.get_state() is None


async def test_start_delete_poll_links_each_poll_to_its_message(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=-1001234567890, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        poll_id = poll.id

    message = FakeMessage("/deletepoll")
    state = _state()

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "Какой опрос удалить? Выберите по номеру:\n"
        f'1. <a href="https://t.me/c/1234567890/42">Игра</a> (id={poll_id})',
        parse_mode="HTML",
    )


async def test_start_delete_poll_does_not_link_an_orphaned_poll(session_maker):
    """Its message is already gone from the chat -- a link would lead nowhere."""
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=-1001234567890, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        await repo.mark_poll_orphaned(session, poll.id)
        poll_id = poll.id

    message = FakeMessage("/deletepoll")
    state = _state()

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "Какой опрос удалить? Выберите по номеру:\n"
        f"1. Игра (id={poll_id}) [опрос удалён, есть только в БД]",
        parse_mode="HTML",
    )


async def test_start_delete_poll_lists_a_poll_with_no_message_as_plain_text(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=-1001234567890, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        poll_id = poll.id

    message = FakeMessage("/deletepoll")
    state = _state()

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        f"Какой опрос удалить? Выберите по номеру:\n1. Игра (id={poll_id})", parse_mode="HTML"
    )


async def test_start_delete_poll_escapes_a_poll_title(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=-1001234567890, title="Кофе & <Игры>", options=[("24.07", None)]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)

    message = FakeMessage("/deletepoll")
    state = _state()

    await start_delete_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    assert "Кофе &amp; &lt;Игры&gt;" in message.answer.await_args.args[0]
