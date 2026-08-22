# /checkme Date Filter + /mygames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict `/checkme` to today-and-future games (it currently shows every dated vote regardless of when it happened), and add a new `/mygames` command that mirrors it for strictly-past games.

**Architecture:** `repo.get_votes_by_user` gains two optional date-bound parameters (`on_or_after`, `before`). `bot/handlers/checkme.py` gains a second handler (`handle_mygames`) sharing the existing chat-resolution/link-building loop via two extracted private helpers, and both handlers now take an injected `timezone: ZoneInfo` to compute "today" fresh on every call — the same approach `jobs.send_due_reminders` already uses. `bot/formatting.py`'s `checkme_line` is renamed to `record_line` (now shared by both commands) and gains `mygames_header`/`mygames_empty_text`.

**Tech Stack:** Python, aiogram 3.30, SQLAlchemy 2.0 async (aiosqlite), pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Reference spec:** `docs/superpowers/specs/2026-08-22-checkme-mygames-date-split-design.md`

---

### Task 1: `repo.get_votes_by_user` date bounds

**Files:**
- Modify: `bot/repo.py:134-145` (the existing `get_votes_by_user` function)
- Test: `tests/test_repo_voting.py`

- [ ] **Step 1: Write the failing tests**

Add `from zoneinfo import ZoneInfo` to the top of `tests/test_repo_voting.py`, so the top of the file reads:

```python
import datetime as dt
from zoneinfo import ZoneInfo

from bot import repo
```

Append these two tests at the end of `tests/test_repo_voting.py`:

```python
async def test_get_votes_by_user_on_or_after_includes_today_and_future_excludes_past(session_maker):
    today = dt.datetime.now(ZoneInfo("Europe/Moscow")).date()
    async with session_maker() as session:
        poll_today = await repo.create_poll(
            session, chat_id=100, title="Сегодня", options=[("Сегодня", today)]
        )
        poll_future = await repo.create_poll(
            session, chat_id=100, title="Будущее", options=[("Будущее", today + dt.timedelta(days=1))]
        )
        poll_past = await repo.create_poll(
            session, chat_id=100, title="Прошлое", options=[("Прошлое", today - dt.timedelta(days=1))]
        )
        option_today = (await repo.get_poll_options(session, poll_today.id))[0]
        option_future = (await repo.get_poll_options(session, poll_future.id))[0]
        option_past = (await repo.get_poll_options(session, poll_past.id))[0]
        await repo.toggle_vote(session, option_today.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_future.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_past.id, user_id=1, username="alice", first_name="Alice")

        rows = await repo.get_votes_by_user(session, user_id=1, on_or_after=today)

    assert [option.id for _, option in rows] == [option_today.id, option_future.id]


async def test_get_votes_by_user_before_includes_past_excludes_today_and_future(session_maker):
    today = dt.datetime.now(ZoneInfo("Europe/Moscow")).date()
    async with session_maker() as session:
        poll_today = await repo.create_poll(
            session, chat_id=100, title="Сегодня", options=[("Сегодня", today)]
        )
        poll_future = await repo.create_poll(
            session, chat_id=100, title="Будущее", options=[("Будущее", today + dt.timedelta(days=1))]
        )
        poll_past = await repo.create_poll(
            session, chat_id=100, title="Прошлое", options=[("Прошлое", today - dt.timedelta(days=1))]
        )
        option_today = (await repo.get_poll_options(session, poll_today.id))[0]
        option_future = (await repo.get_poll_options(session, poll_future.id))[0]
        option_past = (await repo.get_poll_options(session, poll_past.id))[0]
        await repo.toggle_vote(session, option_today.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_future.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_past.id, user_id=1, username="alice", first_name="Alice")

        rows = await repo.get_votes_by_user(session, user_id=1, before=today)

    assert [option.id for _, option in rows] == [option_past.id]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_repo_voting.py -v`
Expected: the two new tests FAIL with `TypeError: get_votes_by_user() got an unexpected keyword argument 'on_or_after'` (and `'before'`).

- [ ] **Step 3: Implement the date bounds**

In `bot/repo.py`, replace the existing `get_votes_by_user` (lines 134-145):

```python
async def get_votes_by_user(session: AsyncSession, user_id: int) -> list[tuple[Poll, Option]]:
    result = await session.execute(
        select(Poll, Option)
        .join(Option, Option.poll_id == Poll.id)
        .join(Vote, Vote.option_id == Option.id)
        .where(
            Vote.user_id == user_id,
            Option.is_deleted.is_(False),
            Option.date.isnot(None),
        )
        .order_by(Option.date, Poll.chat_id, Option.position)
    )
    return list(result.all())
```

with:

```python
async def get_votes_by_user(
    session: AsyncSession,
    user_id: int,
    on_or_after: dt.date | None = None,
    before: dt.date | None = None,
) -> list[tuple[Poll, Option]]:
    conditions = [Vote.user_id == user_id, Option.is_deleted.is_(False), Option.date.isnot(None)]
    if on_or_after is not None:
        conditions.append(Option.date >= on_or_after)
    if before is not None:
        conditions.append(Option.date < before)
    result = await session.execute(
        select(Poll, Option)
        .join(Option, Option.poll_id == Poll.id)
        .join(Vote, Vote.option_id == Option.id)
        .where(*conditions)
        .order_by(Option.date, Poll.chat_id, Option.position)
    )
    return list(result.all())
```

`bot/repo.py` doesn't currently import `datetime` — check the top of the file first. If `import datetime as dt` isn't already there, add it as the first import, before the `from sqlalchemy import select` line:

```python
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Option, Poll, Reminder, ThresholdState, Vote
```

(This import is already present in `bot/repo.py` as of the current codebase — `create_poll`'s signature uses `dt.date | None`. Verify it's there; don't add a duplicate.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_repo_voting.py -v`
Expected: PASS (all tests in the file, old and new).

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_voting.py
git commit -m "feat: add date bounds to repo.get_votes_by_user"
```

---

### Task 2: `formatting.record_line` rename + `/mygames` text helpers

**Files:**
- Modify: `bot/formatting.py:106-118` (rename `checkme_line`, add two new functions)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_formatting.py`, update the import block (currently lines 3-17) — remove `checkme_line`, add `mygames_empty_text`, `mygames_header`, `record_line`:

```python
from bot.formatting import (
    build_message_link,
    checkme_empty_text,
    checkme_header,
    format_option_line,
    mygames_empty_text,
    mygames_header,
    option_date_changed_notification,
    option_deleted_notification,
    option_text_changed_notification,
    poll_message_text,
    record_line,
    reminder_text,
    threshold_dropped_text,
    threshold_reached_text,
    voter_mention,
)
```

Replace the existing `test_checkme_line_escapes_and_links` test (currently lines 155-159) with:

```python
def test_record_line_escapes_and_links():
    line = record_line(1, "Настолки <3", dt.date(2026, 8, 22), "Компания А & Ко", "https://t.me/c/1/2")
    assert line == (
        '1. <a href="https://t.me/c/1/2">22 августа, Настолки &lt;3</a> (Компания А &amp; Ко)'
    )
```

Append these two new tests at the end of the file:

```python
def test_mygames_header_escapes():
    assert mygames_header("Alice & Bob") == "Alice &amp; Bob, вы играли:"


def test_mygames_empty_text_escapes():
    assert mygames_empty_text("Alice & Bob") == "Alice &amp; Bob, у вас нет прошедших игр."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_formatting.py -v`
Expected: FAIL with `ImportError: cannot import name 'record_line' from 'bot.formatting'` (collection error — the whole file fails to collect).

- [ ] **Step 3: Implement the rename and new helpers**

In `bot/formatting.py`, replace the existing `checkme_line` function (lines 106-110):

```python
def checkme_line(
    index: int, option_text: str, option_date: dt.date, chat_title: str, link: str
) -> str:
    label = f"{format_date_ru(option_date)}, {html.escape(option_text)}"
    return f'{index}. <a href="{html.escape(link)}">{label}</a> ({html.escape(chat_title)})'
```

with:

```python
def record_line(
    index: int, option_text: str, option_date: dt.date, chat_title: str, link: str
) -> str:
    label = f"{format_date_ru(option_date)}, {html.escape(option_text)}"
    return f'{index}. <a href="{html.escape(link)}">{label}</a> ({html.escape(chat_title)})'
```

Then append at the end of the file (after `checkme_empty_text`):

```python
def mygames_header(mention: str) -> str:
    return f"{html.escape(mention)}, вы играли:"


def mygames_empty_text(mention: str) -> str:
    return f"{html.escape(mention)}, у вас нет прошедших игр."
```

- [ ] **Step 4: Update the one existing call site**

`bot/handlers/checkme.py` still calls `formatting.checkme_line(...)` — that name no longer exists after Step 3, so this step must land in the *same commit* as the rename or `/checkme` breaks at runtime (and `tests/test_handlers_checkme.py` starts failing) between this task and Task 3.

In `bot/handlers/checkme.py`, change:

```python
        lines.append(formatting.checkme_line(len(lines) + 1, option.text, option.date, chat.title, link))
```

to:

```python
        lines.append(formatting.record_line(len(lines) + 1, option.text, option.date, chat.title, link))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_formatting.py tests/test_handlers_checkme.py -v`
Expected: PASS (all tests in both files — `test_formatting.py` for the rename/new helpers, `test_handlers_checkme.py` unchanged and still green because only the internal call target's name changed, not its behavior).

- [ ] **Step 6: Commit**

```bash
git add bot/formatting.py bot/handlers/checkme.py tests/test_formatting.py
git commit -m "feat: rename checkme_line to record_line, add /mygames text helpers"
```

---

### Task 3: `/checkme` date filter + new `/mygames` handler

**Files:**
- Modify: `bot/handlers/checkme.py` (full rewrite — every existing line changes)
- Test: `tests/test_handlers_checkme.py` (full rewrite — every existing test needs relative dates + the new `timezone` kwarg)

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_handlers_checkme.py` with:

```python
import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from bot import repo
from bot.date_utils import format_date_ru
from bot.handlers.checkme import handle_checkme, handle_mygames


class FakeUser:
    def __init__(self, id, username, first_name):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeChat:
    def __init__(self, id=1, type="private"):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(self, user):
        self.from_user = user
        self.chat = FakeChat()
        self.message_thread_id = None
        self.answer = AsyncMock()


class FakeResolvedChat:
    def __init__(self, title, username=None):
        self.title = title
        self.username = username


TZ = ZoneInfo("Europe/Moscow")


async def test_handle_checkme_lists_dated_votes_across_chats_ordered_by_date(session_maker):
    today = dt.datetime.now(TZ).date()
    date_later = today + dt.timedelta(days=10)
    date_sooner = today + dt.timedelta(days=3)
    async with session_maker() as session:
        poll_a = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Позже", date_later)]
        )
        await repo.set_poll_message(session, poll_a.id, message_id=11)
        poll_b = await repo.create_poll(
            session, chat_id=-100200, title="Игра Б", options=[("Раньше", date_sooner)]
        )
        await repo.set_poll_message(session, poll_b.id, message_id=22)
        option_a = (await repo.get_poll_options(session, poll_a.id))[0]
        option_b = (await repo.get_poll_options(session, poll_b.id))[0]
        await repo.toggle_vote(session, option_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_b.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = lambda chat_id: {
        100: FakeResolvedChat(title="Компания А", username="companya"),
        -100200: FakeResolvedChat(title="Компания Б", username=None),
    }[chat_id]
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, вы записаны:\n"
        f'1. <a href="https://t.me/c/200/22">{format_date_ru(date_sooner)}, Раньше</a> (Компания Б)\n'
        f'2. <a href="https://t.me/companya/11">{format_date_ru(date_later)}, Позже</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_checkme_skips_row_when_get_chat_raises(session_maker):
    today = dt.datetime.now(TZ).date()
    date_ok = today + dt.timedelta(days=1)
    date_broken = today + dt.timedelta(days=2)
    async with session_maker() as session:
        poll_ok = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Ок", date_ok)]
        )
        await repo.set_poll_message(session, poll_ok.id, message_id=11)
        poll_broken = await repo.create_poll(
            session, chat_id=200, title="Игра Б", options=[("Недоступно", date_broken)]
        )
        await repo.set_poll_message(session, poll_broken.id, message_id=22)
        option_ok = (await repo.get_poll_options(session, poll_ok.id))[0]
        option_broken = (await repo.get_poll_options(session, poll_broken.id))[0]
        await repo.toggle_vote(session, option_ok.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_broken.id, user_id=1, username="alice", first_name="Alice")

    def _get_chat(chat_id):
        if chat_id == 200:
            raise RuntimeError("bot was removed from chat")
        return FakeResolvedChat(title="Компания А", username="companya")

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = _get_chat
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, вы записаны:\n"
        f'1. <a href="https://t.me/companya/11">{format_date_ru(date_ok)}, Ок</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_checkme_skips_row_when_no_link_possible(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=-123456789,
            title="Обычная группа",
            options=[("Вариант", today + dt.timedelta(days=1))],
        )
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Обычная группа", username=None)
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, у вас нет записей на игры.", parse_mode="HTML"
    )


async def test_handle_checkme_with_no_votes_sends_empty_text(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username=None, first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Alice, у вас нет записей на игры.", parse_mode="HTML"
    )
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_checkme_includes_todays_game(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[("Сегодня", today)])
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Компания", username="company")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, вы записаны:\n"
        f'1. <a href="https://t.me/company/11">{format_date_ru(today)}, Сегодня</a> (Компания)',
        parse_mode="HTML",
    )


async def test_handle_checkme_excludes_past_games(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("Прошло", today - dt.timedelta(days=1))]
        )
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Компания", username="company")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, у вас нет записей на игры.", parse_mode="HTML"
    )
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_mygames_lists_past_votes_across_chats_ordered_by_date(session_maker):
    today = dt.datetime.now(TZ).date()
    date_older = today - dt.timedelta(days=10)
    date_newer = today - dt.timedelta(days=3)
    async with session_maker() as session:
        poll_a = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Позже", date_newer)]
        )
        await repo.set_poll_message(session, poll_a.id, message_id=11)
        poll_b = await repo.create_poll(
            session, chat_id=-100200, title="Игра Б", options=[("Раньше", date_older)]
        )
        await repo.set_poll_message(session, poll_b.id, message_id=22)
        option_a = (await repo.get_poll_options(session, poll_a.id))[0]
        option_b = (await repo.get_poll_options(session, poll_b.id))[0]
        await repo.toggle_vote(session, option_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_b.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = lambda chat_id: {
        100: FakeResolvedChat(title="Компания А", username="companya"),
        -100200: FakeResolvedChat(title="Компания Б", username=None),
    }[chat_id]
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_mygames(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, вы играли:\n"
        f'1. <a href="https://t.me/c/200/22">{format_date_ru(date_older)}, Раньше</a> (Компания Б)\n'
        f'2. <a href="https://t.me/companya/11">{format_date_ru(date_newer)}, Позже</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_mygames_skips_row_when_get_chat_raises(session_maker):
    today = dt.datetime.now(TZ).date()
    date_ok = today - dt.timedelta(days=1)
    date_broken = today - dt.timedelta(days=2)
    async with session_maker() as session:
        poll_ok = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Ок", date_ok)]
        )
        await repo.set_poll_message(session, poll_ok.id, message_id=11)
        poll_broken = await repo.create_poll(
            session, chat_id=200, title="Игра Б", options=[("Недоступно", date_broken)]
        )
        await repo.set_poll_message(session, poll_broken.id, message_id=22)
        option_ok = (await repo.get_poll_options(session, poll_ok.id))[0]
        option_broken = (await repo.get_poll_options(session, poll_broken.id))[0]
        await repo.toggle_vote(session, option_ok.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_broken.id, user_id=1, username="alice", first_name="Alice")

    def _get_chat(chat_id):
        if chat_id == 200:
            raise RuntimeError("bot was removed from chat")
        return FakeResolvedChat(title="Компания А", username="companya")

    fake_bot = AsyncMock()
    fake_bot.get_chat.side_effect = _get_chat
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_mygames(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, вы играли:\n"
        f'1. <a href="https://t.me/companya/11">{format_date_ru(date_ok)}, Ок</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_mygames_skips_row_when_no_link_possible(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=-123456789,
            title="Обычная группа",
            options=[("Вариант", today - dt.timedelta(days=1))],
        )
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Обычная группа", username=None)
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_mygames(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, у вас нет прошедших игр.", parse_mode="HTML"
    )


async def test_handle_mygames_with_no_votes_sends_empty_text(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username=None, first_name="Alice"))

    await handle_mygames(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "Alice, у вас нет прошедших игр.", parse_mode="HTML"
    )
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_mygames_excludes_todays_and_future_games(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll_today = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("Сегодня", today)]
        )
        await repo.set_poll_message(session, poll_today.id, message_id=11)
        poll_future = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("Завтра", today + dt.timedelta(days=1))]
        )
        await repo.set_poll_message(session, poll_future.id, message_id=12)
        option_today = (await repo.get_poll_options(session, poll_today.id))[0]
        option_future = (await repo.get_poll_options(session, poll_future.id))[0]
        await repo.toggle_vote(session, option_today.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_future.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Компания", username="company")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_mygames(message, bot=fake_bot, session_maker=session_maker, timezone=TZ)

    message.answer.assert_awaited_once_with(
        "@alice, у вас нет прошедших игр.", parse_mode="HTML"
    )
    fake_bot.get_chat.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_handlers_checkme.py -v`
Expected: FAIL — `ImportError: cannot import name 'handle_mygames' from 'bot.handlers.checkme'` (collection error for the whole file).

- [ ] **Step 3: Implement the handler changes**

Replace the entire contents of `bot/handlers/checkme.py` with:

```python
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, repo

router = Router(name="checkme")


async def _build_lines(bot: Bot, rows: list[tuple[repo.Poll, repo.Option]]) -> list[str]:
    chat_cache: dict[int, object | None] = {}
    lines: list[str] = []
    for poll, option in rows:
        if poll.message_id is None:
            continue

        if poll.chat_id not in chat_cache:
            try:
                chat_cache[poll.chat_id] = await bot.get_chat(poll.chat_id)
            except Exception:
                chat_cache[poll.chat_id] = None
        chat = chat_cache[poll.chat_id]

        if chat is None or not chat.title:
            continue

        link = formatting.build_message_link(poll.chat_id, poll.message_id, chat.username)
        if link is None:
            continue

        lines.append(formatting.record_line(len(lines) + 1, option.text, option.date, chat.title, link))
    return lines


async def _answer_with_lines(message: Message, lines: list[str], header: str, empty_text: str) -> None:
    if not lines:
        await message.answer(empty_text, parse_mode="HTML")
        return

    text = header + "\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("checkme"))
async def handle_checkme(message: Message, bot: Bot, session_maker, timezone: ZoneInfo) -> None:
    user = message.from_user
    if user is None:
        return

    today = dt.datetime.now(timezone).date()
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id, on_or_after=today)

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows)
    await _answer_with_lines(
        message, lines, formatting.checkme_header(mention), formatting.checkme_empty_text(mention)
    )


@router.message(Command("mygames"))
async def handle_mygames(message: Message, bot: Bot, session_maker, timezone: ZoneInfo) -> None:
    user = message.from_user
    if user is None:
        return

    today = dt.datetime.now(timezone).date()
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id, before=today)

    mention = formatting.voter_mention(user.username, user.first_name)
    lines = await _build_lines(bot, rows)
    await _answer_with_lines(
        message, lines, formatting.mygames_header(mention), formatting.mygames_empty_text(mention)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_handlers_checkme.py -v`
Expected: PASS (all 11 tests: 6 for `/checkme` — the original 4 plus `includes_todays_game`/`excludes_past_games` — and 5 for `/mygames`).

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/checkme.py tests/test_handlers_checkme.py
git commit -m "feat: filter /checkme to today-and-future games, add /mygames"
```

---

### Task 4: Inject `timezone` into the dispatcher

**Files:**
- Modify: `bot/main.py:111-119` (the `dp.start_polling(...)` call)

- [ ] **Step 1: Add the `timezone` kwarg**

In `bot/main.py`, change:

```python
    try:
        await dp.start_polling(
            bot,
            session_maker=session_maker,
            scheduler=scheduler,
            admin_mention=admin_mention,
            admin_id=config.admin_id,
            threshold_check_callback=jobs.check_threshold,
            threshold_debounce_seconds=config.threshold_debounce_seconds,
        )
```

to:

```python
    try:
        await dp.start_polling(
            bot,
            session_maker=session_maker,
            scheduler=scheduler,
            admin_mention=admin_mention,
            admin_id=config.admin_id,
            threshold_check_callback=jobs.check_threshold,
            threshold_debounce_seconds=config.threshold_debounce_seconds,
            timezone=config.timezone,
        )
```

- [ ] **Step 2: Verify the whole suite still passes**

Run: `./.venv/Scripts/python.exe -m pytest -v`
Expected: all tests PASS, including everything from Tasks 1-3.

- [ ] **Step 3: Verify the module imports cleanly**

Run: `./.venv/Scripts/python.exe -c "import bot.main"`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat: inject timezone into dispatcher for /checkme and /mygames"
```

---

## Self-Review Notes

- **Spec coverage:** date-bound repo query (Task 1) — done; `record_line` rename + `/mygames` text helpers (Task 2) — done; both handlers filtering on the injected `timezone`-derived "today", including the today-inclusive boundary for `/checkme` and today-exclusive boundary for `/mygames` (Task 3, covered by `test_handle_checkme_includes_todays_game` / `test_handle_checkme_excludes_past_games` / `test_handle_mygames_excludes_todays_and_future_games`) — done; DI wiring (Task 4) — done.
- **Type consistency:** `get_votes_by_user(session, user_id, on_or_after=None, before=None)` in Task 1 matches its call sites in Task 3 (`on_or_after=today` in `handle_checkme`, `before=today` in `handle_mygames`). `record_line(index, option_text, option_date, chat_title, link)` signature unchanged from the old `checkme_line` — only the name changes, so the call site in `_build_lines` doesn't need any other adjustment. `mygames_header(mention)`/`mygames_empty_text(mention)` match their call sites in `handle_mygames`.
- **No router registration change needed:** `handle_mygames` is added to the same `router` object already `include_router`-ed in `bot/main.py` — Task 4 only adds the `timezone` kwarg, nothing else in `main.py` changes.
- **Test-date robustness:** all handler/repo tests for the new date-bound behavior compute dates relative to `dt.datetime.now(TZ).date()` at test-run time (matching the existing convention in `tests/test_jobs.py`), so they don't degrade as real time moves forward — unlike the pre-existing `/checkme` tests this plan replaces, which used fixed 2026 calendar dates that would otherwise now sit on the wrong side of the new "today" filter.
