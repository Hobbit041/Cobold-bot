# Orphaned Polls & /deletepoll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop deleted poll messages from cluttering `/editpoll`/`/copypoll` forever, and give the admin an explicit `/deletepoll` command that deletes both the Telegram message and the database record together.

**Architecture:** Add a second valid value for the existing `Poll.status` string column: `"orphaned"`. Two places that already call `bot.edit_message_text` on a specific poll's message (`voting.py` after a vote, `admin_edit.py` after an admin edit) get a narrower exception handler: if Telegram specifically says the message wasn't found, mark that poll `"orphaned"` in the DB as a side effect (visible behavior for the user/admin is unchanged). `/editpoll`/`/copypoll` already filter `status == "active"`, so orphaned polls silently stop appearing there. A new `/deletepoll` command (mirroring `/editpoll`'s list-then-pick UX, works from any chat) lists *all* polls (active and orphaned, so orphaned ones remain reachable for cleanup), deletes the Telegram message (tolerating "already gone"), and hard-deletes the poll + all its related rows from the DB.

**Tech Stack:** Same as the existing bot (Python 3.14, aiogram 3.30, SQLAlchemy async, pytest/pytest-asyncio) — no new dependencies, no schema migration (`status` is a plain unconstrained string column).

---

## File Structure

- Modify: `bot/repo.py` — add `mark_poll_orphaned`, `delete_poll`
- Modify: `bot/handlers/voting.py` — detect "message not found" specifically, mark orphaned
- Modify: `bot/handlers/admin_edit.py` — `_refresh_poll_message`/`_refresh_and_notify` gain a `session_maker` param; same detection or­phans the poll
- Create: `bot/handlers/admin_delete.py` — new `/deletepoll` router
- Modify: `bot/main.py` — register the new router
- Modify: `tests/test_repo_poll.py`, `tests/test_handlers_voting.py`, `tests/test_handlers_admin_edit.py` — new tests
- Create: `tests/test_handlers_admin_delete.py`

No changes to `bot/models.py` (no migration — `status` already a plain `str` column), `bot/handlers/admin_create.py`, `bot/handlers/admin_copy.py`, `bot/keyboards.py`, `bot/formatting.py`.

---

### Task 1: `repo.mark_poll_orphaned` and `repo.delete_poll`

**Files:**
- Modify: `bot/repo.py`
- Modify: `tests/test_repo_poll.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_repo_poll.py`:

```python
async def test_mark_poll_orphaned_sets_status(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.mark_poll_orphaned(session, poll.id)

        refreshed = await repo.get_poll(session, poll.id)
        assert refreshed.status == "orphaned"


async def test_delete_poll_removes_poll_and_all_related_data(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        options = await repo.get_poll_options(session, poll.id)
        kept_option, deleted_option = options
        await repo.toggle_vote(session, kept_option.id, user_id=5, username="alice", first_name="Alice")
        await repo.delete_option(session, deleted_option.id)

        poll_id = poll.id
        kept_option_id = kept_option.id
        deleted_option_id = deleted_option.id

        await repo.delete_poll(session, poll_id)

        assert await repo.get_poll(session, poll_id) is None
        assert await session.get(repo.Option, kept_option_id) is None
        assert await session.get(repo.Option, deleted_option_id) is None
        assert await session.get(repo.ThresholdState, kept_option_id) is None
        assert await session.get(repo.Reminder, kept_option_id) is None
        assert await repo.get_voters(session, kept_option_id) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_poll.py -v`
Expected: FAIL — `AttributeError: module 'bot.repo' has no attribute 'mark_poll_orphaned'` (and then `delete_poll` once the first is fixed)

- [ ] **Step 3: Implement both functions**

In `bot/repo.py`, find:

```python
async def get_poll(session: AsyncSession, poll_id: int) -> Poll | None:
    return await session.get(Poll, poll_id)


# --- Voting ----------------------------------------------------------------
```

Replace it with:

```python
async def get_poll(session: AsyncSession, poll_id: int) -> Poll | None:
    return await session.get(Poll, poll_id)


async def mark_poll_orphaned(session: AsyncSession, poll_id: int) -> None:
    poll = await session.get(Poll, poll_id)
    if poll is not None:
        poll.status = "orphaned"
        await session.commit()


async def delete_poll(session: AsyncSession, poll_id: int) -> None:
    result = await session.execute(select(Option).where(Option.poll_id == poll_id))
    options = list(result.scalars().all())

    for option in options:
        votes = await get_voters(session, option.id)
        for vote in votes:
            await session.delete(vote)

        threshold_state = await session.get(ThresholdState, option.id)
        if threshold_state:
            await session.delete(threshold_state)

        reminder = await session.get(Reminder, option.id)
        if reminder:
            await session.delete(reminder)

        await session.delete(option)

    poll = await session.get(Poll, poll_id)
    await session.delete(poll)
    await session.commit()


# --- Voting ----------------------------------------------------------------
```

(`delete_poll` queries `Option` directly instead of via `get_poll_options`, which filters out already-`is_deleted` options — deleting a whole poll needs to remove *all* its option rows, including ones already soft-deleted through `/editpoll`. It calls `get_voters`, defined further down in this same file in the "Voting" section — that's fine, Python resolves the name when `delete_poll` is actually called, not when the module is parsed; the existing `delete_option` function already relies on the same thing.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_poll.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_poll.py
git commit -m "feat: add repo.mark_poll_orphaned and repo.delete_poll"
```

---

### Task 2: Mark a poll orphaned when voting hits "message not found"

**Files:**
- Modify: `bot/handlers/voting.py`
- Modify: `tests/test_handlers_voting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_handlers_voting.py` (this file already imports `AsyncMock`, `ZoneInfo`, `repo`, `handle_vote_toggle`, `create_scheduler`/`threshold_job_id` — add two more imports to the existing top-of-file import block):

```python
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
```

Then add this test (anywhere after the existing `test_handle_vote_toggle_survives_message_refresh_failure`, which covers the generic-exception case this test is deliberately distinct from):

```python
async def test_handle_vote_toggle_marks_poll_orphaned_when_message_not_found(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        poll_id = poll.id

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    fake_bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(chat_id=100, message_id=42, text="x"),
        message="Bad Request: message to edit not found",
    )
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=10, username="alice", first_name="Alice"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
        threshold_debounce_seconds=900,
    )

    async with session_maker() as session:
        refreshed = await repo.get_poll(session, poll_id)
        assert refreshed.status == "orphaned"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py::test_handle_vote_toggle_marks_poll_orphaned_when_message_not_found -v`
Expected: FAIL — `assert 'active' == 'orphaned'` (the poll's status is never touched yet)

- [ ] **Step 3: Implement the detection**

In `bot/handlers/voting.py`, add this import alongside the existing `from aiogram import Bot, F, Router` line:

```python
from aiogram.exceptions import TelegramBadRequest
```

Then replace:

```python
    try:
        await bot.edit_message_text(
            chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard
        )
    except Exception:
        # The vote is already committed; a stale/undeletable poll message
        # shouldn't block threshold bookkeeping or leave the tapper without
        # a response below.
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
```

with:

```python
    try:
        await bot.edit_message_text(
            chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard
        )
    except Exception as exc:
        if isinstance(exc, TelegramBadRequest) and "not found" in exc.message.lower():
            async with session_maker() as session:
                await repo.mark_poll_orphaned(session, poll.id)
        # The vote is already committed; a stale/undeletable poll message
        # shouldn't block threshold bookkeeping or leave the tapper without
        # a response below.
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py -v`
Expected: PASS (all tests in the file, including the new one — the pre-existing `test_handle_vote_toggle_survives_message_refresh_failure` uses a bare `Exception("message to edit not found")`, not a `TelegramBadRequest`, so it's unaffected by the `isinstance` check and keeps passing unchanged)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/voting.py tests/test_handlers_voting.py
git commit -m "feat: mark a poll orphaned when its message is confirmed gone during voting"
```

---

### Task 3: Mark a poll orphaned when /editpoll hits "message not found"

**Files:**
- Modify: `bot/handlers/admin_edit.py`
- Modify: `tests/test_handlers_admin_edit.py`

- [ ] **Step 1: Write the failing test**

Add these two imports to `tests/test_handlers_admin_edit.py`'s existing top-of-file import block (alongside the existing `from aiogram.fsm.context import FSMContext` line):

```python
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
```

Then add this test at the end of the file:

```python
async def test_apply_new_text_marks_poll_orphaned_when_message_not_found(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))])
        await repo.set_poll_message(session, poll.id, message_id=42)
        poll_id = poll.id

    state = _state()
    fake_bot = AsyncMock()
    fake_bot.edit_message_text.side_effect = TelegramBadRequest(
        method=EditMessageText(chat_id=100, message_id=42, text="x"),
        message="Bad Request: message to edit not found",
    )

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(FakeMessage("text"), state, bot=fake_bot, session_maker=session_maker)
    await apply_new_text(FakeMessage("24.07 (в 19:00)"), state, bot=fake_bot, session_maker=session_maker)

    async with session_maker() as session:
        refreshed = await repo.get_poll(session, poll_id)
        assert refreshed.status == "orphaned"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py::test_apply_new_text_marks_poll_orphaned_when_message_not_found -v`
Expected: FAIL — `AssertionError: assert 'active' == 'orphaned'`. Before Step 3's change, `TelegramBadRequest` from `bot.edit_message_text` just propagates up to `_refresh_and_notify`'s existing generic `except Exception:` (logged, `ok = False`, `apply_new_text` still replies with `_PARTIAL_FAILURE_MESSAGE`) — nothing currently touches `poll.status`, so it stays `"active"`.

- [ ] **Step 3: Thread `session_maker` through `_refresh_and_notify`/`_refresh_poll_message` and detect the error**

In `bot/handlers/admin_edit.py`, add this import alongside the existing `from aiogram import Bot, Router` line:

```python
from aiogram.exceptions import TelegramBadRequest
```

Replace:

```python
async def _refresh_and_notify(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
    voters,
    notification_text: str | None,
) -> bool:
    """Refresh the live poll message and notify voters (if any).

    Both calls hit the Telegram API and can fail independently (e.g. the
    poll's message was manually deleted from the chat, or a transient error).
    Failures here must never propagate: callers rely on always reaching
    state.clear() and always answering the admin, so a bad network call
    doesn't strand the FSM in a state where the *next* unrelated admin
    message gets silently reinterpreted as new option text/date. Returns
    True only if both steps succeeded.
    """
    ok = True
    try:
        await _refresh_poll_message(bot, poll, poll_options, counts, voters_by_option)
    except Exception:
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
        ok = False
```

with:

```python
async def _refresh_and_notify(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
    voters,
    notification_text: str | None,
    session_maker,
) -> bool:
    """Refresh the live poll message and notify voters (if any).

    Both calls hit the Telegram API and can fail independently (e.g. the
    poll's message was manually deleted from the chat, or a transient error).
    Failures here must never propagate: callers rely on always reaching
    state.clear() and always answering the admin, so a bad network call
    doesn't strand the FSM in a state where the *next* unrelated admin
    message gets silently reinterpreted as new option text/date. Returns
    True only if both steps succeeded.
    """
    ok = True
    try:
        await _refresh_poll_message(bot, poll, poll_options, counts, voters_by_option, session_maker)
    except Exception:
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
        ok = False
```

Then replace:

```python
async def _refresh_poll_message(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
) -> None:
    lines = [
        formatting.format_option_line(
            i + 1, opt.text, opt.date, counts[opt.id], voters_by_option.get(opt.id, [])
        )
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, opt.date, counts[opt.id]) for opt in poll_options]
    )
    await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
```

with:

```python
async def _refresh_poll_message(
    bot: Bot,
    poll: Poll,
    poll_options,
    counts: dict[int, int],
    voters_by_option: dict[int, list[str]],
    session_maker,
) -> None:
    lines = [
        formatting.format_option_line(
            i + 1, opt.text, opt.date, counts[opt.id], voters_by_option.get(opt.id, [])
        )
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, opt.date, counts[opt.id]) for opt in poll_options]
    )
    try:
        await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "not found" in exc.message.lower():
            async with session_maker() as session:
                await repo.mark_poll_orphaned(session, poll.id)
        raise
```

- [ ] **Step 4: Update all 4 call sites to pass `session_maker`**

First, in `receive_new_option`, replace:

```python
    success = await _refresh_and_notify(bot, poll, poll_options, counts, voters_by_option, [], None)
```

with:

```python
    success = await _refresh_and_notify(bot, poll, poll_options, counts, voters_by_option, [], None, session_maker)
```

Then — `apply_new_text`, `apply_new_date`, and `_apply_delete` each contain this exact identical block (verify with `grep -n "success = await _refresh_and_notify" bot/handlers/admin_edit.py` — it should list 4 matches total, 1 from the edit above plus these 3):

```python
    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, voters, notification_text
    )
```

Replace **all 3 remaining occurrences** of that exact block with:

```python
    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, voters, notification_text, session_maker
    )
```

(If your editing tool supports a "replace all occurrences" option, use it here — all 3 sites need the identical change. Otherwise apply it 3 times, once per function.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: mark a poll orphaned when /editpoll hits a confirmed-gone message"
```

---

### Task 4: New `/deletepoll` command

**Files:**
- Create: `bot/handlers/admin_delete.py`
- Create: `tests/test_handlers_admin_delete.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers_admin_delete.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_delete.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.handlers.admin_delete'`

- [ ] **Step 3: Implement `bot/handlers/admin_delete.py`**

```python
"""Admin-only /deletepoll: permanently delete a poll's database record and its
live Telegram message.

Works from any chat, including a DM with the bot (like /editpoll) -- the
message to delete is identified by the poll's own stored chat_id/message_id,
not by whatever chat the admin happens to run /deletepoll from.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import repo
from bot.handlers.dialog_cleanup import cleanup_and_answer
from bot.models import Poll

router = Router(name="admin_delete")
logger = logging.getLogger(__name__)


class DeletePollStates(StatesGroup):
    waiting_poll_selection = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("deletepoll"))
async def start_delete_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_answer(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll))
        polls = list(result.scalars().all())

    if not polls:
        await cleanup_and_answer(message, state, "Опросов нет.", scheduler=scheduler)
        return

    lines = [
        f"{i + 1}. {poll.title} (id={poll.id})"
        + (" [опрос удалён, есть только в БД]" if poll.status == "orphaned" else "")
        for i, poll in enumerate(polls)
    ]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(DeletePollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message,
        state,
        "Какой опрос удалить? Выберите по номеру:\n" + "\n".join(lines),
        scheduler=scheduler,
    )


@router.message(DeletePollStates.waiting_poll_selection)
async def select_poll_to_delete(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    data = await state.get_data()
    poll_ids = data["poll_ids"]
    try:
        index = int(message.text.strip()) - 1
        if index < 0:
            raise IndexError
        poll_id = poll_ids[index]
    except (ValueError, IndexError, AttributeError):
        await cleanup_and_answer(
            message, state, "Некорректный номер. Попробуйте снова.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        poll = await repo.get_poll(session, poll_id)
        chat_id = poll.chat_id
        message_id = poll.message_id

    if message_id is not None:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.exception(
                "Failed to delete message %s in chat %s for poll %s", message_id, chat_id, poll_id
            )

    async with session_maker() as session:
        await repo.delete_poll(session, poll_id)

    await state.clear()
    await cleanup_and_answer(message, state, "Опрос удалён.", scheduler=scheduler)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_delete.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_delete.py tests/test_handlers_admin_delete.py
git commit -m "feat: add /deletepoll to delete a poll's message and database record together"
```

---

### Task 5: Register the new router

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Add the import and registration**

In `bot/main.py`, replace:

```python
from bot.handlers import admin_copy, admin_create, admin_edit, dialog_control, voting
```

with:

```python
from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, dialog_control, voting
```

Then replace:

```python
    # dialog_control (/cancel) must be included before admin_create/admin_edit/admin_copy:
    # see bot/handlers/dialog_control.py's module docstring for why the order matters.
    dp.include_router(dialog_control.router)
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(admin_copy.router)
    dp.include_router(voting.router)
```

with:

```python
    # dialog_control (/cancel) must be included before admin_create/admin_edit/admin_copy/admin_delete:
    # see bot/handlers/dialog_control.py's module docstring for why the order matters.
    dp.include_router(dialog_control.router)
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(admin_copy.router)
    dp.include_router(admin_delete.router)
    dp.include_router(voting.router)
```

- [ ] **Step 2: Confirm `bot.main` still imports cleanly**

Run: `source .venv/Scripts/activate && python -c "import bot.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add bot/main.py
git commit -m "feat: register the /deletepoll router"
```

---

### Task 6: Full-suite regression check and running-bot restart note

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `source .venv/Scripts/activate && python -m pytest -v`
Expected: PASS (all pre-existing tests plus the new ones from Tasks 1-4 — no regressions)

- [ ] **Step 2: Report to the user that the running bot process needs a restart**

This plan changes application code (`bot/repo.py`, `bot/handlers/voting.py`,
`bot/handlers/admin_edit.py`, `bot/handlers/admin_delete.py`, `bot/main.py`).
No database schema/migration changed (`status` is a plain string column, no
new column, no `ALTER TABLE` needed) — existing `"active"` polls are
unaffected, and any poll that later gets orphaned just gets a new string
value in an existing column. Tell the user to restart the running bot
process to pick up `/deletepoll` and the orphan-detection behavior, and
offer to do it for them (restarting bothost.ru means pushing/redeploying,
per this project's earlier persistence fix — the "подключить общее
хранилище данных" toggle they enabled should keep poll data intact through
this and future redeploys).
