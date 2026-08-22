# Открытый доступ + /stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the single-hardcoded-admin restriction on poll management (`/newpoll`, `/editpoll`, `/deletepoll`, `/copypoll`, `/cancel`), replacing it with per-chat Telegram admin/creator checks, and add a `/stats` command that gives the bot's developer (still identified by `ADMIN_ID`) a list of chats the bot is used in with each one's last-poll date, while everyone else gets a short command-list help text.

**Architecture:** A new `bot/authz.py` module centralizes "is this user an admin/creator of this chat" checks (via `bot.get_chat_member`, reusing the pattern already used by `/checkme`'s delete button) plus a generic list-filtering helper. Every poll-management handler drops its `admin_id`-based gate and calls into `bot/authz.py` instead, checking the *target* chat, not a global allow-list. A new `bot/handlers/stats.py` router adds `/stats`, backed by a new `repo.get_chat_poll_stats()` query and a new `date_utils.format_date_ru_with_year()` formatter. `ADMIN_ID`/`ADMIN_USERNAME` env vars are unchanged; `ADMIN_ID` now only gates `/stats`.

**Tech Stack:** Python, aiogram 3, SQLAlchemy (async, SQLite), pytest + pytest-asyncio (auto mode).

**Design doc:** `docs/superpowers/specs/2026-08-23-open-access-and-stats-design.md`

---

## Task 1: `bot/authz.py` — shared chat-admin authorization helpers

**Files:**
- Create: `bot/authz.py`
- Test: `tests/test_authz.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_authz.py`:

```python
from unittest.mock import AsyncMock

from bot.authz import filter_by_chat_admin, is_chat_admin


class FakeChatMember:
    def __init__(self, status):
        self.status = status


async def test_is_chat_admin_true_for_administrator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is True


async def test_is_chat_admin_true_for_creator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="creator")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is True


async def test_is_chat_admin_false_for_plain_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="member")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is False


async def test_is_chat_admin_false_when_lookup_raises():
    bot = AsyncMock()
    bot.get_chat_member.side_effect = RuntimeError("bot not in chat")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is False


async def test_filter_by_chat_admin_keeps_only_administered_chats():
    bot = AsyncMock()

    async def _get_chat_member(chat_id, user_id):
        statuses = {-1: "administrator", -2: "member"}
        return FakeChatMember(status=statuses[chat_id])

    bot.get_chat_member.side_effect = _get_chat_member
    items = [("a", -1), ("b", -2), ("c", -1)]

    kept = await filter_by_chat_admin(bot, items, user_id=7, chat_id_getter=lambda x: x[1])

    assert kept == [("a", -1), ("c", -1)]
    assert bot.get_chat_member.await_count == 2  # one call per distinct chat_id, cached


async def test_filter_by_chat_admin_returns_empty_for_missing_user_id():
    bot = AsyncMock()

    kept = await filter_by_chat_admin(bot, [("a", -1)], user_id=None, chat_id_getter=lambda x: x[1])

    assert kept == []
    bot.get_chat_member.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_authz.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'bot.authz'`

- [ ] **Step 3: Implement `bot/authz.py`**

```python
"""Chat-scoped authorization checks shared by the poll-management handlers.

Replaces the old single-hardcoded-ADMIN_ID gate: instead of one allow-listed
user, any command that manages a poll checks whether the caller is an
admin/creator of that poll's own chat (via Telegram's own membership data),
so the bot works for any group without a central allow-list.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from aiogram import Bot

T = TypeVar("T")


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """True if user_id is an administrator or creator of chat_id.

    Any failure to look up membership (bot not in the chat, chat gone, etc.)
    is treated as "not authorized" rather than propagating -- callers must
    fail closed, not open.
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("administrator", "creator")


async def filter_by_chat_admin(
    bot: Bot, items: list[T], user_id: int | None, chat_id_getter: Callable[[T], int]
) -> list[T]:
    """Keep only the items whose chat (via chat_id_getter) user_id administers.

    Each distinct chat is checked only once no matter how many items map to
    it, so filtering N polls across 2 chats costs 2 get_chat_member calls.
    """
    if user_id is None:
        return []

    cache: dict[int, bool] = {}
    kept: list[T] = []
    for item in items:
        chat_id = chat_id_getter(item)
        if chat_id not in cache:
            cache[chat_id] = await is_chat_admin(bot, chat_id, user_id)
        if cache[chat_id]:
            kept.append(item)
    return kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_authz.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/authz.py tests/test_authz.py
git commit -m "feat: add shared chat-admin authorization helpers"
```

---

## Task 2: Refactor `/checkme`'s delete button to use `bot.authz.is_chat_admin`

**Files:**
- Modify: `bot/handlers/checkme.py`
- Test: `tests/test_handlers_checkme.py` (no changes needed — this is a pure refactor, existing tests must keep passing unmodified)

- [ ] **Step 1: Edit the import**

In `bot/handlers/checkme.py`, change:

```python
from bot import formatting, keyboards, repo
```

to:

```python
from bot import formatting, keyboards, repo
from bot.authz import is_chat_admin
```

- [ ] **Step 2: Replace the inline admin check**

In `handle_delete_button`, change:

```python
    allowed = presser_id == requester_id
    if not allowed:
        try:
            member = await bot.get_chat_member(callback.message.chat.id, presser_id)
            allowed = member.status in ("administrator", "creator")
        except Exception:
            allowed = False
```

to:

```python
    allowed = presser_id == requester_id or await is_chat_admin(bot, callback.message.chat.id, presser_id)
```

(Python's `or` short-circuits, so `is_chat_admin` is never called — and `get_chat_member` never awaited — when `presser_id == requester_id`, matching the existing `test_handle_delete_button_requester_deletes` expectation.)

- [ ] **Step 3: Run the existing tests to verify the refactor didn't change behavior**

Run: `python -m pytest tests/test_handlers_checkme.py -v`
Expected: PASS (all existing tests, unmodified)

- [ ] **Step 4: Commit**

```bash
git add bot/handlers/checkme.py
git commit -m "refactor: use shared is_chat_admin in checkme's delete button"
```

---

## Task 3: `repo.get_chat_poll_stats` — per-chat last-poll-date query

**Files:**
- Modify: `bot/repo.py`
- Test: `tests/test_repo_poll.py`

- [ ] **Step 1: Write the failing tests**

At the end of `tests/test_repo_poll.py`, change:

```python
async def test_delete_poll_on_nonexistent_poll_id_is_a_noop(session_maker):
    async with session_maker() as session:
        await repo.delete_poll(session, 999999)
```

to:

```python
async def test_delete_poll_on_nonexistent_poll_id_is_a_noop(session_maker):
    async with session_maker() as session:
        await repo.delete_poll(session, 999999)


async def test_get_chat_poll_stats_returns_empty_list_when_no_polls(session_maker):
    async with session_maker() as session:
        stats = await repo.get_chat_poll_stats(session)

    assert stats == []


async def test_get_chat_poll_stats_groups_by_chat_and_returns_latest_created_at(session_maker):
    async with session_maker() as session:
        poll_a1 = await repo.create_poll(session, chat_id=100, title="A1", options=[("x", None)])
        poll_a2 = await repo.create_poll(session, chat_id=100, title="A2", options=[("x", None)])
        poll_b = await repo.create_poll(session, chat_id=200, title="B", options=[("x", None)])

        poll_a1.created_at = dt.datetime(2026, 8, 10, 10, 0, 0)
        poll_a2.created_at = dt.datetime(2026, 8, 20, 10, 0, 0)
        poll_b.created_at = dt.datetime(2026, 8, 15, 10, 0, 0)
        await session.commit()

        stats = await repo.get_chat_poll_stats(session)

    assert stats == [
        (100, dt.datetime(2026, 8, 20, 10, 0, 0)),
        (200, dt.datetime(2026, 8, 15, 10, 0, 0)),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repo_poll.py -v -k get_chat_poll_stats`
Expected: FAIL — `AttributeError: module 'bot.repo' has no attribute 'get_chat_poll_stats'`

- [ ] **Step 3: Implement `repo.get_chat_poll_stats`**

In `bot/repo.py`, change the import line:

```python
from sqlalchemy import select
```

to:

```python
from sqlalchemy import func, select
```

Then add, right after `get_poll` (before `mark_poll_orphaned`):

```python
async def get_chat_poll_stats(session: AsyncSession) -> list[tuple[int, dt.datetime]]:
    """Distinct chat_ids that have at least one poll, each with its most
    recent poll's created_at, newest first.

    Used by /stats. Note: there's no separate table tracking which chats the
    bot has been added to -- a chat whose every poll has been hard-deleted
    via /deletepoll will no longer appear here, even if the bot is still a
    member of it.
    """
    result = await session.execute(
        select(Poll.chat_id, func.max(Poll.created_at))
        .group_by(Poll.chat_id)
        .order_by(func.max(Poll.created_at).desc())
    )
    return list(result.all())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_repo_poll.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_poll.py
git commit -m "feat: add repo.get_chat_poll_stats for /stats"
```

---

## Task 4: `date_utils.format_date_ru_with_year`

**Files:**
- Modify: `bot/date_utils.py`
- Test: `tests/test_date_utils.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_date_utils.py`, change the import line:

```python
from bot.date_utils import DateParseError, format_date_ru, parse_date_input, parse_option_input
```

to:

```python
from bot.date_utils import (
    DateParseError,
    format_date_ru,
    format_date_ru_with_year,
    parse_date_input,
    parse_option_input,
)
```

Then, at the end of the file, change:

```python
def test_parse_option_input_blank_text_before_separator_raises():
    with pytest.raises(DateParseError):
        parse_option_input(" | 24.07.2026")
```

to:

```python
def test_parse_option_input_blank_text_before_separator_raises():
    with pytest.raises(DateParseError):
        parse_option_input(" | 24.07.2026")


def test_format_date_ru_with_year():
    assert format_date_ru_with_year(dt.date(2026, 8, 23)) == "23 августа 2026"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_date_utils.py -v -k with_year`
Expected: FAIL — `ImportError: cannot import name 'format_date_ru_with_year'`

- [ ] **Step 3: Implement `format_date_ru_with_year`**

In `bot/date_utils.py`, right after `format_date_ru`, add:

```python
def format_date_ru_with_year(d: dt.date) -> str:
    return f"{d.day} {MONTHS_RU[d.month]} {d.year}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_date_utils.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add bot/date_utils.py tests/test_date_utils.py
git commit -m "feat: add format_date_ru_with_year for /stats"
```

---

## Task 5: `/stats` command

**Files:**
- Create: `bot/handlers/stats.py`
- Test: `tests/test_handlers_stats.py`
- Modify: `bot/main.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers_stats.py`:

```python
import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from bot import repo
from bot.handlers.stats import handle_stats

TZ = ZoneInfo("Europe/Moscow")


class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, user_id):
        self.from_user = FakeUser(user_id)
        self.answer = AsyncMock()


class FakeResolvedChat:
    def __init__(self, title):
        self.title = title


async def test_handle_stats_non_admin_gets_help_text(session_maker):
    message = FakeMessage(user_id=2)
    fake_bot = AsyncMock()

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    text = message.answer.await_args.args[0]
    assert "/newpoll" in text
    assert "/editpoll" in text
    assert "/deletepoll" in text
    assert "/copypoll" in text
    assert "/checkme" in text
    assert "/cancel" in text
    assert "/stats" not in text
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_stats_admin_with_no_groups(session_maker):
    message = FakeMessage(user_id=1)
    fake_bot = AsyncMock()

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with("Бот пока не используется ни в одной группе.")


async def test_handle_stats_admin_lists_groups_with_last_poll_date(session_maker):
    async with session_maker() as session:
        poll_a = await repo.create_poll(session, chat_id=100, title="A", options=[("x", None)])
        poll_b = await repo.create_poll(session, chat_id=200, title="B", options=[("x", None)])
        poll_a.created_at = dt.datetime(2026, 8, 20, 10, 0, 0)
        poll_b.created_at = dt.datetime(2026, 8, 22, 10, 0, 0)
        await session.commit()

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = lambda chat_id: {
        100: FakeResolvedChat(title="Компания А"),
        200: FakeResolvedChat(title="Компания Б"),
    }[chat_id]
    message = FakeMessage(user_id=1)

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Бот используется в 2 групп(ах):\n"
        "«Компания Б» — последний опрос: 22 августа 2026\n"
        "«Компания А» — последний опрос: 20 августа 2026"
    )


async def test_handle_stats_admin_marks_unreachable_chat(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=999, title="C", options=[("x", None)])
        poll.created_at = dt.datetime(2026, 8, 1, 10, 0, 0)
        await session.commit()

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = RuntimeError("bot was removed from chat")
    message = FakeMessage(user_id=1)

    await handle_stats(message, bot=fake_bot, session_maker=session_maker, admin_id=1, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Бот используется в 1 групп(ах):\n"
        "«группа 999 (бот больше не состоит в ней)» — последний опрос: 1 августа 2026"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_handlers_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.handlers.stats'`

- [ ] **Step 3: Implement `bot/handlers/stats.py`**

```python
"""`/stats`: developer-only usage overview; everyone else gets a command list.

ADMIN_ID from `.env` is no longer used to gate poll management -- it's kept
purely so the bot's developer can send /stats and see which chats the bot
has been used in and when each last saw a poll created. Anyone else who
sends /stats gets a short list of available commands instead.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import date_utils, repo

router = Router(name="stats")

_HELP_TEXT = (
    "Этот бот помогает организовывать опросы по датам в группах.\n"
    "\n"
    "Доступные команды:\n"
    "/newpoll — создать новый опрос\n"
    "/editpoll — изменить опрос (текст/дату варианта, добавить вариант, порядок, название)\n"
    "/deletepoll — удалить опрос полностью\n"
    "/copypoll — скопировать существующий опрос в текущий чат\n"
    "/checkme — посмотреть, на какие предстоящие игры вы записаны\n"
    "/cancel — отменить текущий диалог с ботом\n"
    "\n"
    "Управление опросами (/newpoll, /editpoll, /deletepoll, /copypoll) доступно "
    "только администраторам группы. Чтобы бот мог публиковать и обновлять "
    "опросы, добавьте его в группу и выдайте права администратора."
)

_NO_GROUPS_TEXT = "Бот пока не используется ни в одной группе."


async def _describe_chat(bot: Bot, chat_id: int) -> str:
    try:
        chat = await bot.get_chat(chat_id)
        return chat.title or str(chat_id)
    except Exception:
        return f"группа {chat_id} (бот больше не состоит в ней)"


@router.message(Command("stats"))
async def handle_stats(
    message: Message, bot: Bot, session_maker, admin_id: int, timezone: ZoneInfo
) -> None:
    user = message.from_user
    if user is None:
        return

    if user.id != admin_id:
        await message.answer(_HELP_TEXT)
        return

    async with session_maker() as session:
        rows = await repo.get_chat_poll_stats(session)

    if not rows:
        await message.answer(_NO_GROUPS_TEXT)
        return

    lines = []
    for chat_id, last_created_at in rows:
        title = await _describe_chat(bot, chat_id)
        local_date = last_created_at.replace(tzinfo=dt.timezone.utc).astimezone(timezone).date()
        lines.append(f"«{title}» — последний опрос: {date_utils.format_date_ru_with_year(local_date)}")

    text = f"Бот используется в {len(rows)} групп(ах):\n" + "\n".join(lines)
    await message.answer(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_stats.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Register the router in `bot/main.py`**

Change:

```python
from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, checkme, dialog_control, voting
```

to:

```python
from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, checkme, dialog_control, stats, voting
```

Change:

```python
    dp.include_router(voting.router)
    dp.include_router(checkme.router)
```

to:

```python
    dp.include_router(voting.router)
    dp.include_router(checkme.router)
    dp.include_router(stats.router)
```

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `python -m pytest -v`
Expected: PASS (all tests, including the pre-existing suite)

- [ ] **Step 7: Commit**

```bash
git add bot/handlers/stats.py tests/test_handlers_stats.py bot/main.py
git commit -m "feat: add /stats command for the bot developer"
```

---

## Task 6: Open up `/newpoll` (admin_create.py) to any chat admin

**Files:**
- Modify: `bot/handlers/admin_create.py`
- Modify: `tests/test_handlers_admin_create.py` (full rewrite)

- [ ] **Step 1: Rewrite `tests/test_handlers_admin_create.py` to express the new authorization model**

Replace the entire file content with:

```python
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

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
from bot import repo
from bot.models import Poll
from bot.scheduler import create_scheduler, dialog_timeout_job_id


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeChatMember:
    def __init__(self, status):
        self.status = status


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


def _admin_bot():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    return bot


async def test_start_create_poll_in_private_chat_proceeds_for_any_user():
    message = FakeMessage("/newpoll", user_id=2, chat_type="private")
    state = _state()

    await start_create_poll(message, state, bot=AsyncMock())

    assert await state.get_state() == CreatePollStates.waiting_title.state


async def test_start_create_poll_in_group_rejects_non_chat_admin():
    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")
    message = FakeMessage("/newpoll", user_id=2, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_create_poll(message, state, bot=fake_bot)

    message.answer.assert_awaited_once_with("Эта команда доступна только администраторам этого чата.")
    assert await state.get_state() is None


async def test_start_create_poll_in_group_allows_chat_admin():
    message = FakeMessage("/newpoll", user_id=2, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_create_poll(message, state, bot=_admin_bot())

    assert await state.get_state() == CreatePollStates.waiting_title.state


async def test_full_create_flow_persists_poll(session_maker):
    state = _state()

    admin_message = FakeMessage("/newpoll", user_id=1)
    await start_create_poll(admin_message, state, bot=AsyncMock())
    assert await state.get_state() == CreatePollStates.waiting_title.state

    await receive_title(FakeMessage("Игра в апреле"), state)
    assert await state.get_state() == CreatePollStates.waiting_options.state

    await receive_option(FakeMessage("24.07 | 24.07.2026"), state)
    await receive_option(FakeMessage("25.07 | 25.07.2026"), state)
    data = await state.get_data()
    assert len(data["options"]) == 2

    fake_bot = _admin_bot()
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


async def test_receive_target_chat_rejects_non_chat_admin(session_maker):
    state = _state()

    await start_create_poll(FakeMessage("/newpoll", user_id=1), state, bot=AsyncMock())
    await receive_title(FakeMessage("Игра"), state)
    await receive_option(FakeMessage("24.07 | 24.07.2026"), state)

    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")
    await finish_options(FakeMessage("/done"), state, bot=fake_bot, session_maker=session_maker)

    target_message = FakeMessage("-100123")
    await receive_target_chat(target_message, state, bot=fake_bot, session_maker=session_maker)

    target_message.answer.assert_awaited_once_with(
        "Эта команда доступна только администраторам этого чата."
    )
    fake_bot.send_message.assert_not_awaited()
    assert await state.get_state() is None

    async with session_maker() as session:
        assert (await session.execute(select(Poll))).scalars().all() == []


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


async def test_receive_option_accepts_text_with_no_date():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("Во что поиграть")
    await receive_option(message, state)

    data = await state.get_data()
    assert data["options"] == [{"text": "Во что поиграть", "date": None}]
    assert "Добавлено: Во что поиграть." in message.answer.await_args.args[0]


async def test_full_create_flow_persists_poll_with_dateless_option(session_maker):
    state = _state()

    await start_create_poll(FakeMessage("/newpoll", user_id=1), state, bot=AsyncMock())
    await receive_title(FakeMessage("Игра в апреле"), state)
    await receive_option(FakeMessage("Во что поиграть"), state)

    fake_bot = _admin_bot()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 999})()

    await finish_options(FakeMessage("/done"), state, bot=fake_bot, session_maker=session_maker)
    await receive_target_chat(FakeMessage("-100123"), state, bot=fake_bot, session_maker=session_maker)

    async with session_maker() as session:
        result = await session.execute(select(Poll))
        poll = result.scalar_one()
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "Во что поиграть"
        assert options[0].date is None


async def test_receive_option_still_accepts_pipe_separator():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("24.07 | 24.07.2026")
    await receive_option(message, state)

    data = await state.get_data()
    assert data["options"] == [{"text": "24.07", "date": "2026-07-24"}]


async def test_receive_option_rejects_blank_text():
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[])

    message = FakeMessage("   ")
    await receive_option(message, state)

    message.answer.assert_awaited_once()
    data = await state.get_data()
    assert data["options"] == []


async def test_receive_target_chat_cleans_up_when_send_fails(session_maker):
    state = _state()

    admin_message = FakeMessage("/newpoll", user_id=1)
    await start_create_poll(admin_message, state, bot=AsyncMock())
    await receive_title(FakeMessage("Игра в апреле"), state)
    await receive_option(FakeMessage("24.07 | 24.07.2026"), state)

    fake_bot = _admin_bot()
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
    fake_bot = _admin_bot()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 777})()

    admin_message = FakeMessage("/newpoll", user_id=1, chat_type="supergroup", chat_id=-500)
    await start_create_poll(admin_message, state, bot=fake_bot)
    assert await state.get_state() == CreatePollStates.waiting_title.state

    await receive_title(
        FakeMessage("Игра", chat_type="supergroup", chat_id=-500), state
    )
    await receive_option(
        FakeMessage("24.07 | 24.07.2026", chat_type="supergroup", chat_id=-500), state
    )

    done_message = FakeMessage("/done", chat_type="supergroup", chat_id=-500)
    await finish_options(done_message, state, bot=fake_bot, session_maker=session_maker)

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
    fake_bot = _admin_bot()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 778})()

    admin_message = FakeMessage(
        "/newpoll", user_id=1, chat_type="supergroup", chat_id=-500, message_thread_id=42
    )
    await start_create_poll(admin_message, state, bot=fake_bot)
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
    await start_create_poll(admin_message, state, bot=AsyncMock())
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
    fake_bot = _admin_bot()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 779})()

    start_message = FakeMessage(
        "/newpoll", user_id=1, chat_type="group", chat_id=-501, message_id=1
    )
    await start_create_poll(start_message, state, bot=fake_bot)
    start_message.delete.assert_awaited_once()

    title_message = FakeMessage("Игра", chat_type="group", chat_id=-501, message_id=2)
    await receive_title(title_message, state)
    title_message.delete.assert_awaited_once()
    # Deletes the bot's previous prompt ("Введите название опроса:") too.
    title_message.bot.delete_message.assert_awaited_once()


async def test_newpoll_in_group_arms_idle_timeout_and_clears_it_on_finish(session_maker, tmp_path):
    state = _state()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = _admin_bot()
    fake_bot.send_message.return_value = type("Sent", (), {"message_id": 780})()

    start_message = FakeMessage("/newpoll", user_id=9, chat_type="supergroup", chat_id=-600)
    await start_create_poll(start_message, state, bot=fake_bot, scheduler=scheduler)
    assert scheduler.get_job(dialog_timeout_job_id(-600, 9)) is not None

    await receive_title(FakeMessage("Игра", user_id=9, chat_type="supergroup", chat_id=-600), state, scheduler=scheduler)
    await receive_option(
        FakeMessage("24.07 | 24.07.2026", user_id=9, chat_type="supergroup", chat_id=-600), state, scheduler=scheduler
    )
    done_message = FakeMessage("/done", user_id=9, chat_type="supergroup", chat_id=-600)
    done_message.answer.return_value = type("Sent", (), {"message_id": 951})()
    await finish_options(done_message, state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler)

    assert await state.get_state() is None
    assert scheduler.get_job(dialog_timeout_job_id(-600, 9)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_handlers_admin_create.py -v`
Expected: FAIL — `TypeError: start_create_poll() got an unexpected keyword argument 'bot'` (and similar `admin_id`-related failures)

- [ ] **Step 3: Update `bot/handlers/admin_create.py`**

Change the module docstring and imports:

```python
"""Admin-only conversation flow for creating a new poll via /newpoll.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo.
"""

from __future__ import annotations

import datetime as dt

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import date_utils, formatting, keyboards, repo
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish

router = Router(name="admin_create")
```

to:

```python
"""Conversation flow for creating a new poll via /newpoll.

Available to any user; publishing into a chat other than a private DM with
the bot requires being an admin/creator of that chat (bot.authz.is_chat_admin)
-- when /newpoll is typed directly in a group, that check happens
immediately; when it's typed in a DM, the target chat isn't known until
receive_target_chat resolves it, so the check happens there instead, right
before the poll is published.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo.
"""

from __future__ import annotations

import datetime as dt

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import date_utils, formatting, keyboards, repo
from bot.authz import is_chat_admin
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish

router = Router(name="admin_create")

_NOT_CHAT_ADMIN_MESSAGE = "Эта команда доступна только администраторам этого чата."
```

Change:

```python
def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("newpoll"))
async def start_create_poll(message: Message, state: FSMContext, admin_id: int, scheduler=None) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_finish(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    await state.set_state(CreatePollStates.waiting_title)
```

to:

```python
@router.message(Command("newpoll"))
async def start_create_poll(message: Message, state: FSMContext, bot: Bot, scheduler=None) -> None:
    if message.chat.type != "private":
        user_id = message.from_user.id if message.from_user is not None else None
        if user_id is None or not await is_chat_admin(bot, message.chat.id, user_id):
            await cleanup_and_finish(message, state, _NOT_CHAT_ADMIN_MESSAGE, scheduler=scheduler)
            return

    await state.set_state(CreatePollStates.waiting_title)
```

Change (in `receive_target_chat`):

```python
    if chat_id is None:
        await cleanup_and_answer(
            message,
            state,
            "Не удалось определить чат. Перешлите сообщение из чата или пришлите его id.",
            scheduler=scheduler,
        )
        return

    data = await state.get_data()
```

to:

```python
    if chat_id is None:
        await cleanup_and_answer(
            message,
            state,
            "Не удалось определить чат. Перешлите сообщение из чата или пришлите его id.",
            scheduler=scheduler,
        )
        return

    user_id = message.from_user.id if message.from_user is not None else None
    if user_id is None or not await is_chat_admin(bot, chat_id, user_id):
        await cleanup_and_finish(message, state, _NOT_CHAT_ADMIN_MESSAGE, scheduler=scheduler)
        return

    data = await state.get_data()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_admin_create.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_create.py tests/test_handlers_admin_create.py
git commit -m "feat: open /newpoll to any chat admin instead of one hardcoded id"
```

---

## Task 7: Open up `/editpoll` (admin_edit.py) — filter poll list by chat admin

**Files:**
- Modify: `bot/handlers/admin_edit.py`
- Modify: `tests/test_handlers_admin_edit.py` (targeted edits)

- [ ] **Step 1: Add `FakeChatMember` + `_admin_bot()` helper and new filtering tests to the test file**

In `tests/test_handlers_admin_edit.py`, change:

```python
def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


async def test_edit_text_notifies_existing_voters(tmp_path, session_maker):
```

to:

```python
def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


class FakeChatMember:
    def __init__(self, status):
        self.status = status


def _admin_bot():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    return bot


async def test_start_edit_poll_hides_polls_from_chats_user_does_not_administer(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )

    message = FakeMessage("/editpoll", user_id=2)
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")

    await start_edit_poll(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Активных опросов нет.")
    assert await state.get_state() is None


async def test_start_edit_poll_only_lists_polls_from_administered_chats(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Моя группа", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.create_poll(
            session, chat_id=200, title="Чужая группа", options=[("25.07", dt.date(2026, 7, 25))]
        )

    message = FakeMessage("/editpoll", user_id=1)
    state = _state()
    fake_bot = AsyncMock()

    async def _get_chat_member(chat_id, user_id):
        statuses = {100: "administrator", 200: "member"}
        return FakeChatMember(status=statuses[chat_id])

    fake_bot.get_chat_member.side_effect = _get_chat_member

    await start_edit_poll(message, state, bot=fake_bot, session_maker=session_maker)

    listed_text = message.answer.await_args.args[0]
    assert "Моя группа" in listed_text
    assert "Чужая группа" not in listed_text


async def test_edit_text_notifies_existing_voters(tmp_path, session_maker):
```

- [ ] **Step 2: Bulk-update every unchanged `start_edit_poll` call site**

Still in `tests/test_handlers_admin_edit.py`, run one `replace_all` edit:

old_string:
```python
    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
```

new_string:
```python
    await start_edit_poll(FakeMessage("/editpoll"), state, bot=_admin_bot(), session_maker=session_maker)
```

with `replace_all=True`. This covers all 16 call sites that use the plain `FakeMessage("/editpoll")` form (in `test_edit_text_notifies_existing_voters`, `test_delete_option_notifies_and_removes_it`, `test_edit_date_notifies_existing_voters`, `test_edit_text_without_voters_sends_no_notification`, `test_edit_text_survives_refresh_failure_and_still_replies`, `test_apply_new_text_shows_voter_names_for_all_options`, `test_apply_new_text_notification_uses_poll_message_thread_id`, `test_addoption_appends_new_option_and_refreshes_poll_message`, `test_addoption_rejects_invalid_format_and_stays_in_state`, `test_addoption_accepts_text_with_no_date`, `test_apply_new_date_on_option_with_no_prior_date`, `test_edit_text_on_option_without_date_sends_no_notification`, `test_delete_option_without_date_sends_no_notification`, `test_select_poll_rejects_zero_instead_of_wrapping_to_last_poll`, `test_select_option_rejects_zero_instead_of_wrapping_to_last_option`, `test_apply_new_text_marks_poll_orphaned_when_message_not_found`, `test_revoll_reorders_options_and_refreshes_message`, `test_revoll_rejects_invalid_order_and_stays_in_state`, `test_revoll_rejects_unicode_digit_like_order_and_stays_in_state`).

- [ ] **Step 3: Fix the two call sites that use a named `start_message` instead**

In `test_editpoll_started_in_group_deletes_admin_messages_and_previous_prompts`, change:

```python
    start_message = FakeMessage("/editpoll", chat_type="group", chat_id=-500, message_id=1)
    await start_edit_poll(start_message, state, admin_id=1, session_maker=session_maker)
    start_message.delete.assert_awaited_once()
```

to:

```python
    fake_bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    start_message = FakeMessage("/editpoll", chat_type="group", chat_id=-500, message_id=1)
    await start_edit_poll(start_message, state, bot=fake_bot, session_maker=session_maker)
    start_message.delete.assert_awaited_once()
```

In `test_editpoll_in_group_arms_idle_timeout_and_clears_it_on_finish`, change:

```python
    start_message = FakeMessage("/editpoll", user_id=3, chat_type="group", chat_id=-500, message_id=1)
    await start_edit_poll(start_message, state, admin_id=3, session_maker=session_maker, scheduler=scheduler)
    assert scheduler.get_job(dialog_timeout_job_id(-500, 3)) is not None
```

to:

```python
    fake_bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    start_message = FakeMessage("/editpoll", user_id=3, chat_type="group", chat_id=-500, message_id=1)
    await start_edit_poll(start_message, state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler)
    assert scheduler.get_job(dialog_timeout_job_id(-500, 3)) is not None
```

- [ ] **Step 4: Run tests to verify they fail against the old implementation**

Run: `python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: FAIL — `TypeError: start_edit_poll() got an unexpected keyword argument 'bot'`

- [ ] **Step 5: Update `bot/handlers/admin_edit.py`**

Change the module docstring and imports:

```python
"""Admin-only conversation flow for editing an existing poll via /editpoll.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo. Any pending 15-minute threshold-debounce timer is
cancelled through bot.scheduler when its option is deleted.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import date_utils, formatting, keyboards, repo
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll
from bot.scheduler import cancel_threshold_check

router = Router(name="admin_edit")
```

to:

```python
"""Conversation flow for editing an existing poll via /editpoll.

Available to any user; the list of polls offered is filtered down to only
those in chats the requester administers/created
(bot.authz.filter_by_chat_admin), so /editpoll never reveals another chat's
poll titles to someone who isn't that chat's admin.

Thin aiogram glue: state transitions live here, but parsing/formatting/
persistence logic is delegated to bot.date_utils / bot.formatting /
bot.keyboards / bot.repo. Any pending 15-minute threshold-debounce timer is
cancelled through bot.scheduler when its option is deleted.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import date_utils, formatting, keyboards, repo
from bot.authz import filter_by_chat_admin
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll
from bot.scheduler import cancel_threshold_check

router = Router(name="admin_edit")
```

Change:

```python
def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("editpoll"))
async def start_edit_poll(
    message: Message, state: FSMContext, admin_id: int, session_maker, scheduler=None
) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_finish(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
```

to:

```python
@router.message(Command("editpoll"))
async def start_edit_poll(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    user_id = message.from_user.id if message.from_user is not None else None

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    polls = await filter_by_chat_admin(bot, polls, user_id, lambda p: p.chat_id)

    if not polls:
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (all tests, including the 2 new filtering tests)

- [ ] **Step 7: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: open /editpoll to any chat admin, filtered per chat"
```

---

## Task 8: Open up `/deletepoll` (admin_delete.py) — filter poll list by chat admin

**Files:**
- Modify: `bot/handlers/admin_delete.py`
- Modify: `tests/test_handlers_admin_delete.py` (full rewrite)

- [ ] **Step 1: Rewrite `tests/test_handlers_admin_delete.py`**

Replace the entire file content with:

```python
import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.admin_delete import DeletePollStates, select_poll_to_delete, start_delete_poll
from bot.scheduler import create_scheduler, message_deletion_job_id


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


def _admin_bot():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
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
    fake_bot.delete_message.side_effect = Exception("message to delete not found")
    message = FakeMessage("1")

    await select_poll_to_delete(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Опрос удалён.")
    async with session_maker() as session:
        assert await repo.get_poll(session, poll_id) is None


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
```

- [ ] **Step 2: Run tests to verify they fail against the old implementation**

Run: `python -m pytest tests/test_handlers_admin_delete.py -v`
Expected: FAIL — `TypeError: start_delete_poll() got an unexpected keyword argument 'bot'`

- [ ] **Step 3: Update `bot/handlers/admin_delete.py`**

Change the module docstring and imports:

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
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
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
        await cleanup_and_finish(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    async with session_maker() as session:
        # Unlike /editpoll and /copypoll, deliberately not filtered to status
        # == "active" -- an already-"orphaned" poll must stay reachable here,
        # or it would be permanently unreachable/undeletable from any command.
        result = await session.execute(select(Poll))
        polls = list(result.scalars().all())

    if not polls:
```

to:

```python
"""/deletepoll: permanently delete a poll's database record and its live
Telegram message.

Works from any chat, including a DM with the bot (like /editpoll) -- the
message to delete is identified by the poll's own stored chat_id/message_id,
not by whatever chat the caller happens to run /deletepoll from. Available to
any user; the list of polls offered is filtered down to only those in chats
the requester administers/created (bot.authz.filter_by_chat_admin).
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
from bot.authz import filter_by_chat_admin
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll

router = Router(name="admin_delete")
logger = logging.getLogger(__name__)


class DeletePollStates(StatesGroup):
    waiting_poll_selection = State()


@router.message(Command("deletepoll"))
async def start_delete_poll(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    user_id = message.from_user.id if message.from_user is not None else None

    async with session_maker() as session:
        # Unlike /editpoll and /copypoll, deliberately not filtered to status
        # == "active" -- an already-"orphaned" poll must stay reachable here,
        # or it would be permanently unreachable/undeletable from any command.
        result = await session.execute(select(Poll))
        polls = list(result.scalars().all())

    polls = await filter_by_chat_admin(bot, polls, user_id, lambda p: p.chat_id)

    if not polls:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_admin_delete.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_delete.py tests/test_handlers_admin_delete.py
git commit -m "feat: open /deletepoll to any chat admin, filtered per chat"
```

---

## Task 9: Open up `/copypoll` (admin_copy.py) — chat-admin check + filtered source list

**Files:**
- Modify: `bot/handlers/admin_copy.py`
- Modify: `tests/test_handlers_admin_copy.py` (full rewrite)

- [ ] **Step 1: Rewrite `tests/test_handlers_admin_copy.py`**

Replace the entire file content with:

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


def _admin_bot():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")
    return bot


async def test_start_copy_poll_rejects_non_chat_admin():
    message = FakeMessage("/copypoll", user_id=2, chat_type="supergroup", chat_id=-500)
    state = _state()
    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")

    await start_copy_poll(message, state, bot=fake_bot, session_maker=None)

    message.answer.assert_awaited_once_with("Эта команда доступна только администраторам этого чата.")
    assert await state.get_state() is None


async def test_start_copy_poll_rejects_private_chat():
    message = FakeMessage("/copypoll", user_id=1, chat_type="private")
    state = _state()

    await start_copy_poll(message, state, bot=AsyncMock(), session_maker=None)

    message.answer.assert_awaited_once_with(
        "Эта команда работает только в группе, в теме которую нужно скопировать опрос."
    )
    assert await state.get_state() is None


async def test_start_copy_poll_reports_no_active_polls(session_maker):
    message = FakeMessage("/copypoll", user_id=1, chat_type="supergroup", chat_id=-500)
    state = _state()

    await start_copy_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

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

    await start_copy_poll(message, state, bot=_admin_bot(), session_maker=session_maker)

    assert await state.get_state() == CopyPollStates.waiting_poll_selection.state
    data = await state.get_data()
    assert data["target_chat_id"] == -500
    assert data["target_message_thread_id"] == 42
    listed_text = message.answer.await_args.args[0]
    assert "Игра в апреле" in listed_text


async def test_start_copy_poll_only_lists_active_polls_from_administered_chats(session_maker):
    async with session_maker() as session:
        await repo.create_poll(
            session, chat_id=100, title="Моя группа", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.create_poll(
            session, chat_id=200, title="Чужая группа", options=[("25.07", dt.date(2026, 7, 25))]
        )

    message = FakeMessage("/copypoll", user_id=1, chat_type="supergroup", chat_id=-500)
    state = _state()
    fake_bot = AsyncMock()

    async def _get_chat_member(chat_id, user_id):
        statuses = {-500: "administrator", 100: "administrator", 200: "member"}
        return FakeChatMember(status=statuses[chat_id])

    fake_bot.get_chat_member.side_effect = _get_chat_member

    await start_copy_poll(message, state, bot=fake_bot, session_maker=session_maker)

    listed_text = message.answer.await_args.args[0]
    assert "Моя группа" in listed_text
    assert "Чужая группа" not in listed_text


async def test_select_poll_to_copy_rejects_invalid_number(session_maker):
    state = _state()
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[1], target_chat_id=-500, target_message_thread_id=None)

    message = FakeMessage("banana", chat_type="supergroup", chat_id=-500)
    fake_bot = AsyncMock()

    await select_poll_to_copy(message, state, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with("Некорректный номер. Попробуйте снова.")
    assert await state.get_state() == CopyPollStates.waiting_poll_selection.state


async def test_select_poll_to_copy_rejects_zero(session_maker):
    state = _state()
    await state.set_state(CopyPollStates.waiting_poll_selection)
    await state.update_data(poll_ids=[1, 2, 3], target_chat_id=-500, target_message_thread_id=None)

    message = FakeMessage("0", chat_type="supergroup", chat_id=-500)
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

- [ ] **Step 2: Run tests to verify they fail against the old implementation**

Run: `python -m pytest tests/test_handlers_admin_copy.py -v`
Expected: FAIL — `TypeError: start_copy_poll() got an unexpected keyword argument 'bot'`

- [ ] **Step 3: Update `bot/handlers/admin_copy.py`**

Replace the entire file content with:

```python
"""/copypoll: copy an existing poll's title and options into the chat/topic
where the command is run.

Only works when run directly in a group (never in a private chat with the
bot) -- unlike /newpoll's DM flow, there's no step here that lets a private
conversation express *which* chat/topic the copy should be published into.
Available to any admin/creator of the chat the command is run in (checked via
bot.authz.is_chat_admin); the list of source polls offered is further
filtered down to only those in chats the requester administers/created
(bot.authz.filter_by_chat_admin), so /copypoll never reveals another chat's
poll titles to someone who isn't that chat's admin.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import repo
from bot.authz import filter_by_chat_admin, is_chat_admin
from bot.handlers.admin_create import create_and_publish_poll
from bot.handlers.dialog_cleanup import cleanup_and_answer, cleanup_and_finish
from bot.models import Poll

router = Router(name="admin_copy")

_NOT_CHAT_ADMIN_MESSAGE = "Эта команда доступна только администраторам этого чата."


class CopyPollStates(StatesGroup):
    waiting_poll_selection = State()


@router.message(Command("copypoll"))
async def start_copy_poll(
    message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None
) -> None:
    if message.chat.type == "private":
        await cleanup_and_finish(
            message,
            state,
            "Эта команда работает только в группе, в теме которую нужно скопировать опрос.",
            scheduler=scheduler,
        )
        return

    user_id = message.from_user.id if message.from_user is not None else None
    if user_id is None or not await is_chat_admin(bot, message.chat.id, user_id):
        await cleanup_and_finish(message, state, _NOT_CHAT_ADMIN_MESSAGE, scheduler=scheduler)
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    polls = await filter_by_chat_admin(bot, polls, user_id, lambda p: p.chat_id)

    if not polls:
        await cleanup_and_finish(message, state, "Активных опросов нет.", scheduler=scheduler)
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
        if index < 0:
            raise IndexError
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_admin_copy.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_copy.py tests/test_handlers_admin_copy.py
git commit -m "feat: open /copypoll to any chat admin, filtered per chat"
```

---

## Task 10: Remove the hardcoded-admin gate from `/cancel` (dialog_control.py)

**Files:**
- Modify: `bot/handlers/dialog_control.py`
- Modify: `tests/test_handlers_dialog_control.py` (full rewrite)

- [ ] **Step 1: Rewrite `tests/test_handlers_dialog_control.py`**

Replace the entire file content with:

```python
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


async def test_cancel_with_no_active_dialog_says_nothing_to_cancel():
    message = FakeMessage(user_id=1)
    state = _state()

    await cancel_dialog(message, state)

    message.answer.assert_awaited_once_with("Нечего отменять.")


async def test_cancel_clears_active_create_poll_dialog():
    message = FakeMessage(user_id=1)
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    await state.update_data(options=[{"text": "24.07", "date": "2026-07-24"}])

    await cancel_dialog(message, state)

    assert await state.get_state() is None
    message.answer.assert_awaited_once_with("Действие отменено.")


async def test_cancel_in_group_deletes_messages_and_cancels_pending_timeout(tmp_path):
    message = FakeMessage(user_id=1, chat_type="group", chat_id=-500, message_id=7)
    message.answer.return_value = type("Sent", (), {"message_id": 950})()
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    schedule_dialog_timeout(scheduler, -500, 1, None, callback=_noop_dialog_timeout)

    await cancel_dialog(message, state, scheduler=scheduler)

    message.delete.assert_awaited_once()
    assert await state.get_state() is None
    assert scheduler.get_job(dialog_timeout_job_id(-500, 1)) is None


async def test_cancel_needs_no_admin_check_state_is_already_scoped_to_caller():
    # aiogram's FSM state is keyed by (chat_id, user_id), so whichever state
    # object a /cancel handler receives already belongs to that same caller --
    # there's no "someone else's dialog" it could ever reach.
    message = FakeMessage(user_id=2)
    state = _state()
    await state.set_state(CreatePollStates.waiting_options)

    await cancel_dialog(message, state)

    assert await state.get_state() is None
    message.answer.assert_awaited_once_with("Действие отменено.")
```

- [ ] **Step 2: Run tests to verify they fail against the old implementation**

Run: `python -m pytest tests/test_handlers_dialog_control.py -v`
Expected: FAIL — `TypeError: cancel_dialog() missing 1 required positional argument: 'admin_id'` (calls no longer pass it)

- [ ] **Step 3: Update `bot/handlers/dialog_control.py`**

Replace the entire file content with:

```python
"""/cancel: escape hatch out of a stuck /newpoll or /editpoll dialog.

Must be included in the Dispatcher before admin_create/admin_edit/admin_copy/admin_delete's routers
(see bot/main.py) -- those routers have catch-all message handlers per FSM
state with no Command filter, so without this router matching first, "/cancel"
typed mid-dialog would itself be swallowed as if it were poll title/option/etc
text instead of being recognized as a request to exit.

No authorization check is needed here: aiogram's FSM state is already scoped
to (chat_id, user_id), so /cancel can only ever clear the caller's own dialog.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.dialog_cleanup import cleanup_and_finish

router = Router(name="dialog_control")


@router.message(Command("cancel"))
async def cancel_dialog(message: Message, state: FSMContext, scheduler=None) -> None:
    if await state.get_state() is None:
        await cleanup_and_finish(message, state, "Нечего отменять.", scheduler=scheduler)
        return

    await cleanup_and_finish(message, state, "Действие отменено.", scheduler=scheduler)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_handlers_dialog_control.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/dialog_control.py tests/test_handlers_dialog_control.py
git commit -m "feat: drop hardcoded-admin gate from /cancel"
```

---

## Task 11: Update docs (`README.md`, `.env.example`)

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Update the commands section in `README.md`**

Change:

```markdown
## Команды бота (только для администратора)

- `/newpoll` — создать опрос: название → варианты (`Текст | ДД.ММ.ГГГГ`, вместо `|` подойдёт `/` или `\`) → `/done` → chat id или пересылка сообщения из чата
- `/editpoll` — изменить/удалить вариант существующего опроса; на шаге выбора варианта можно прислать любой текст (не номер и не команду), чтобы переименовать опрос
```

to:

```markdown
## Команды бота

- `/newpoll` — создать опрос: название → варианты (`Текст | ДД.ММ.ГГГГ`, вместо `|` подойдёт `/` или `\`) → `/done` → chat id или пересылка сообщения из чата
- `/editpoll` — изменить/удалить вариант существующего опроса; на шаге выбора варианта можно прислать любой текст (не номер и не команду), чтобы переименовать опрос
- `/deletepoll` — удалить опрос полностью (из чата и из базы)
- `/copypoll` — скопировать существующий опрос в текущий чат/тему
- `/checkme` — посмотреть, на какие предстоящие игры вы записаны
- `/cancel` — отменить текущий диалог с ботом
- `/stats` — для разработчика бота (`ADMIN_ID` из `.env`): список групп, где используется бот, и дата последнего опроса в каждой; для всех остальных — краткая справка по командам

`/newpoll`, `/editpoll`, `/deletepoll` и `/copypoll` доступны только
администраторам/создателю того чата, в котором создаётся, редактируется или
удаляется опрос — права проверяются через Telegram (`get_chat_member`), а не
по списку конкретных пользователей.
```

- [ ] **Step 2: Update the `ADMIN_ID` comment in `.env.example`**

Change:

```
BOT_TOKEN=123456:ABC-DEF...
ADMIN_ID=123456789
ADMIN_USERNAME=your_username
```

to:

```
BOT_TOKEN=123456:ABC-DEF...
# Telegram user id of the bot's developer -- grants access to /stats (list of
# chats + last poll date). Does not restrict who can manage polls; that's
# governed by each chat's own Telegram admin/creator status instead.
ADMIN_ID=123456789
ADMIN_USERNAME=your_username
```

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: reflect open access + /stats in README and .env.example"
```

---

## Task 12: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest -v`
Expected: PASS — every test in `tests/` (old and new) passes, 0 failures, 0 errors.

- [ ] **Step 2: Manually confirm no leftover references to the old gate**

Run: `python -m pytest -v` already covers behavior; additionally confirm no stale symbol remains:

Run (Bash/PowerShell):
```bash
grep -rn "_is_admin\b" bot/ || echo "none found"
```
Expected: `none found` (the `_is_admin` helper was removed from every handler in Tasks 6–10).

- [ ] **Step 3: Report completion**

No commit needed for this task if Steps 1–2 pass clean (nothing changed). If either step surfaces a problem, fix it, re-run, and commit the fix with an appropriate message before considering the plan done.

---

## Self-Review Notes

- **Spec coverage:** Section 1 (authorization) → Tasks 6–10. Section 2 (`/stats`) → Task 5. Section 3 (repo query) → Task 3. Section 4 ("what doesn't change") → verified no task touches `admin_mention`/`ADMIN_USERNAME`/voting/checkme's read paths/scheduler. Section 5 (tests) → every listed test file has a corresponding task; `tests/test_authz.py` and `tests/test_handlers_stats.py` are new, matching the spec's "new" list.
- **Type consistency:** `filter_by_chat_admin(bot, items, user_id, chat_id_getter)` signature is identical across Tasks 7, 8, 9. `is_chat_admin(bot, chat_id, user_id)` signature is identical across Tasks 2, 6, 9. `repo.get_chat_poll_stats(session) -> list[tuple[int, dt.datetime]]` matches its use in Task 5's `handle_stats`. `date_utils.format_date_ru_with_year(d: dt.date) -> str` matches its use in Task 5.
- **Placeholder scan:** no TBD/TODO markers; every step carries complete code or an exact shell command with expected output.
