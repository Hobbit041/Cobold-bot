# /copypoll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/copypoll` admin command that copies an existing poll's title and (non-deleted) options into a brand-new poll published in the chat/topic where the command is run — no votes, no announced/reminder state carried over. Only works when run directly in a group; refuses in private chats.

**Architecture:** Reuse `bot/handlers/admin_create.py`'s existing "create poll in DB + publish message + roll back on send failure" logic by lifting it out of the `/newpoll` FSM's `state.get_data()` coupling so it takes `title`/`options` as plain parameters. A new `bot/handlers/admin_copy.py` router implements `/copypoll` with a one-step FSM (list active polls → admin picks a number → copy), mirroring `/editpoll`'s existing poll-selection UX in `bot/handlers/admin_edit.py`, then calls the now-shared publish function.

**Tech Stack:** Same as the existing bot (Python 3.14, aiogram 3.30, SQLAlchemy async, pytest/pytest-asyncio) — no new dependencies, no schema changes.

---

## File Structure

- Modify: `bot/handlers/admin_create.py` — `_create_and_publish_poll` becomes public `create_and_publish_poll`, takes `title`/`options` as parameters instead of reading them from FSM state
- Create: `bot/handlers/admin_copy.py` — new `/copypoll` router (`CopyPollStates`, `start_copy_poll`, `select_poll_to_copy`)
- Modify: `bot/main.py` — register the new router
- Create: `tests/test_handlers_admin_copy.py` — new tests
- Modify: `tests/test_handlers_admin_create.py` — no changes needed (it only calls the public FSM entry points, never the renamed helper directly), included here only as the regression check in Task 1

No changes to `bot/models.py`, `bot/repo.py`, `bot/formatting.py`, `bot/keyboards.py`, or `bot/db.py` — `repo.create_poll` already produces fresh `ThresholdState(announced=False)`/`Reminder(sent=False)` per option and no `Vote` rows, which is exactly the "no votes carried over" behavior this feature needs for free.

---

### Task 1: Make `create_and_publish_poll` reusable outside the `/newpoll` FSM flow

**Files:**
- Modify: `bot/handlers/admin_create.py`

This is a behavior-preserving refactor (no new user-visible behavior), so the safety net is the existing test suite staying green before and after, rather than a new failing test.

- [ ] **Step 1: Run the existing tests as a baseline**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_create.py -v`
Expected: PASS (all currently-passing tests — this is the baseline the refactor below must not break)

- [ ] **Step 2: Rename the helper and make it accept `title`/`options` directly**

In `bot/handlers/admin_create.py`, replace:

```python
async def _create_and_publish_poll(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session_maker,
    chat_id: int,
    message_thread_id: int | None = None,
    scheduler=None,
) -> None:
    data = await state.get_data()
    title = data["title"]
    options = [
        (opt["text"], dt.date.fromisoformat(opt["date"]) if opt["date"] else None)
        for opt in data["options"]
    ]

    async with session_maker() as session:
```

with:

```python
def _parse_stored_options(raw_options: list[dict]) -> list[tuple[str, dt.date | None]]:
    return [
        (opt["text"], dt.date.fromisoformat(opt["date"]) if opt["date"] else None)
        for opt in raw_options
    ]


async def create_and_publish_poll(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session_maker,
    chat_id: int,
    title: str,
    options: list[tuple[str, dt.date | None]],
    message_thread_id: int | None = None,
    scheduler=None,
) -> None:
    async with session_maker() as session:
```

(everything below `async with session_maker() as session:` in the function body is unchanged)

- [ ] **Step 3: Generalize the group-chat failure message**

It currently tells the admin to retry via `/done`, which only makes sense for `/newpoll`'s flow. `/copypoll` (added in Task 2) will reuse this same function but has no `/done` step, so the message needs to be command-agnostic.

In the same function, replace:

```python
                await cleanup_and_answer(
                    message,
                    state,
                    "Не удалось опубликовать опрос в этом чате. Проверьте, что у бота есть права "
                    "отправлять сообщения, и повторите /done.",
                    scheduler=scheduler,
                )
```

with:

```python
                await cleanup_and_answer(
                    message,
                    state,
                    "Не удалось опубликовать опрос в этом чате. Проверьте, что у бота есть права "
                    "отправлять сообщения, и повторите попытку.",
                    scheduler=scheduler,
                )
```

- [ ] **Step 4: Update the two call sites**

In `finish_options`, replace:

```python
    target_chat_id = data.get("target_chat_id")
    if target_chat_id is not None:
        await _create_and_publish_poll(
            message,
            state,
            bot,
            session_maker,
            target_chat_id,
            data.get("target_message_thread_id"),
            scheduler=scheduler,
        )
        return
```

with:

```python
    target_chat_id = data.get("target_chat_id")
    if target_chat_id is not None:
        await create_and_publish_poll(
            message,
            state,
            bot,
            session_maker,
            target_chat_id,
            data["title"],
            _parse_stored_options(options),
            data.get("target_message_thread_id"),
            scheduler=scheduler,
        )
        return
```

In `receive_target_chat`, replace:

```python
    await _create_and_publish_poll(message, state, bot, session_maker, chat_id, scheduler=scheduler)
```

with:

```python
    data = await state.get_data()
    await create_and_publish_poll(
        message,
        state,
        bot,
        session_maker,
        chat_id,
        data["title"],
        _parse_stored_options(data.get("options", [])),
        scheduler=scheduler,
    )
```

- [ ] **Step 5: Run the tests again to confirm no regression**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_create.py -v`
Expected: PASS (same tests as Step 1, now exercising the refactored code — behavior must be identical)

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/admin_create.py
git commit -m "refactor: let create_and_publish_poll take title/options directly"
```

---

### Task 2: New `/copypoll` command

**Files:**
- Create: `bot/handlers/admin_copy.py`
- Create: `tests/test_handlers_admin_copy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers_admin_copy.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_copy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.handlers.admin_copy'` (the module doesn't exist yet)

- [ ] **Step 3: Implement `bot/handlers/admin_copy.py`**

```python
"""Admin-only /copypoll: copy an existing poll's title and options into the
chat/topic where the command is run.

Only works when run directly in a group (never in a private chat with the
bot) -- unlike /newpoll's DM flow, there's no step here that lets a private
conversation express *which* chat/topic the copy should be published into.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import repo
from bot.handlers.admin_create import create_and_publish_poll
from bot.handlers.dialog_cleanup import cleanup_and_answer
from bot.models import Poll

router = Router(name="admin_copy")


class CopyPollStates(StatesGroup):
    waiting_poll_selection = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("copypoll"))
async def start_copy_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_answer(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    if message.chat.type == "private":
        await cleanup_and_answer(
            message,
            state,
            "Эта команда работает только в группе, в теме которую нужно скопировать опрос.",
            scheduler=scheduler,
        )
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
        await cleanup_and_answer(message, state, "Активных опросов нет.", scheduler=scheduler)
        return

    lines = [f"{i + 1}. {poll.title} (id={poll.id})" for i, poll in enumerate(polls)]
    await state.update_data(
        poll_ids=[poll.id for poll in polls],
        target_chat_id=message.chat.id,
        target_message_thread_id=message.message_thread_id,
    )
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await cleanup_and_answer(
        message,
        state,
        "Какой опрос скопировать? Выберите по номеру:\n" + "\n".join(lines),
        scheduler=scheduler,
    )


@router.message(CopyPollStates.waiting_poll_selection)
async def select_poll_to_copy(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    data = await state.get_data()
    poll_ids = data["poll_ids"]
    try:
        index = int(message.text.strip()) - 1
        poll_id = poll_ids[index]
    except (ValueError, IndexError, AttributeError):
        await cleanup_and_answer(
            message, state, "Некорректный номер. Попробуйте снова.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        source_poll = await repo.get_poll(session, poll_id)
        source_options = await repo.get_poll_options(session, poll_id)
        title = source_poll.title
        options = [(opt.text, opt.date) for opt in source_options]

    await create_and_publish_poll(
        message,
        state,
        bot,
        session_maker,
        data["target_chat_id"],
        title,
        options,
        data["target_message_thread_id"],
        scheduler=scheduler,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_copy.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_copy.py tests/test_handlers_admin_copy.py
git commit -m "feat: add /copypoll to copy an existing poll's title/options into the current topic"
```

---

### Task 3: Register the new router

**Files:**
- Modify: `bot/main.py`

- [ ] **Step 1: Add the import and registration**

In `bot/main.py`, replace:

```python
from bot.handlers import admin_create, admin_edit, dialog_control, voting
```

with:

```python
from bot.handlers import admin_copy, admin_create, admin_edit, dialog_control, voting
```

Then replace:

```python
    # dialog_control (/cancel) must be included before admin_create/admin_edit:
    # see bot/handlers/dialog_control.py's module docstring for why the order matters.
    dp.include_router(dialog_control.router)
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(voting.router)
```

with:

```python
    # dialog_control (/cancel) must be included before admin_create/admin_edit/admin_copy:
    # see bot/handlers/dialog_control.py's module docstring for why the order matters.
    dp.include_router(dialog_control.router)
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(admin_copy.router)
    dp.include_router(voting.router)
```

- [ ] **Step 2: Confirm `bot.main` still imports cleanly**

Run: `source .venv/Scripts/activate && python -c "import bot.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add bot/main.py
git commit -m "feat: register the /copypoll router"
```

---

### Task 4: Full-suite regression check and running-bot restart note

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `source .venv/Scripts/activate && python -m pytest -v`
Expected: PASS (all pre-existing tests plus the 6 new ones from Task 2 — no regressions; Task 1's refactor is behavior-preserving and every existing test already passed against it in Task 1 Step 5)

- [ ] **Step 2: Report to the user that the running bot process needs a restart**

This plan changes application code (`bot/handlers/admin_create.py`, `bot/handlers/admin_copy.py`, `bot/main.py`). If a bot instance is already running (started via `python -m bot.main` or the deployed container), it's running the old in-memory code and won't pick up `/copypoll` until restarted. No database schema changed, so a restart is the only step needed — existing polls/votes/data are untouched. Tell the user to restart the running bot process to pick up the change, and offer to do it for them.
