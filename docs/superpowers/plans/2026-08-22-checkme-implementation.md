# /checkme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/checkme` command, callable by any user, that replies in the calling chat with a numbered, clickable list of every dated game the caller is currently signed up for, across every chat the bot manages.

**Architecture:** A new `repo.get_votes_by_user` query joins `Vote → Option → Poll` for one user. `bot/formatting.py` gains pure functions to build a `t.me` deep link per chat and to assemble HTML-escaped list lines (this is the first message in the codebase to use `parse_mode="HTML"`, so all interpolated text must be escaped). A new thin handler in `bot/handlers/checkme.py` wires the two together, resolving each poll's chat title via `bot.get_chat` (cached per call) and silently dropping any row it can't fully resolve.

**Tech Stack:** Python, aiogram 3.30, SQLAlchemy 2.0 async (aiosqlite), pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Reference spec:** `docs/superpowers/specs/2026-08-22-checkme-design.md`

---

### Task 1: `repo.get_votes_by_user`

**Files:**
- Modify: `bot/repo.py` (insert after `get_voters`, which ends at line 131 — right before the `# --- Edit / delete option ---` section comment on line 134)
- Test: `tests/test_repo_voting.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repo_voting.py`:

```python
import datetime as dt


async def test_get_votes_by_user_orders_by_date_and_excludes_dateless_and_other_users(session_maker):
    async with session_maker() as session:
        poll_a = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра А",
            options=[("Позже", dt.date(2026, 9, 1)), ("Без даты", None)],
        )
        poll_b = await repo.create_poll(
            session, chat_id=200, title="Игра Б", options=[("Раньше", dt.date(2026, 8, 1))]
        )
        options_a = await repo.get_poll_options(session, poll_a.id)
        options_b = await repo.get_poll_options(session, poll_b.id)
        dated_a, dateless_a = options_a[0], options_a[1]
        dated_b = options_b[0]

        await repo.toggle_vote(session, dated_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dateless_a.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dated_b.id, user_id=1, username="alice", first_name="Alice")
        await repo.toggle_vote(session, dated_b.id, user_id=2, username="bob", first_name="Bob")

        rows = await repo.get_votes_by_user(session, user_id=1)

    assert [(poll.id, option.id) for poll, option in rows] == [
        (poll_b.id, dated_b.id),
        (poll_a.id, dated_a.id),
    ]


async def test_get_votes_by_user_excludes_deleted_option(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")
        option.is_deleted = True
        await session.commit()

        rows = await repo.get_votes_by_user(session, user_id=1)

    assert rows == []


async def test_get_votes_by_user_with_no_votes_returns_empty_list(session_maker):
    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user_id=999)

    assert rows == []
```

The `import datetime as dt` at the top of this new block conflicts with nothing in the file (the file currently has no top-level import block beyond `from bot import repo`) — add it as a new top-of-file import line instead of inline: the final top of `tests/test_repo_voting.py` should read:

```python
import datetime as dt

from bot import repo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_repo_voting.py -v`
Expected: the three new tests FAIL with `AttributeError: module 'bot.repo' has no attribute 'get_votes_by_user'`.

- [ ] **Step 3: Implement `get_votes_by_user`**

In `bot/repo.py`, insert this function immediately after `get_voters` (after line 131, before the `# --- Edit / delete option ---` comment):

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

No new imports are needed — `select`, `Poll`, `Option`, `Vote` are already imported at the top of `bot/repo.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repo_voting.py -v`
Expected: PASS (all tests in the file, old and new).

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_voting.py
git commit -m "feat: add repo.get_votes_by_user for /checkme"
```

---

### Task 2: `formatting.build_message_link` and checkme text helpers

**Files:**
- Modify: `bot/formatting.py`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_formatting.py` (and add `build_message_link, checkme_empty_text, checkme_header, checkme_line` to the existing `from bot.formatting import (...)` block):

```python
def test_build_message_link_with_username():
    assert build_message_link(-1001234567890, 42, "somechat") == "https://t.me/somechat/42"


def test_build_message_link_supergroup_without_username():
    assert build_message_link(-1001234567890, 42, None) == "https://t.me/c/1234567890/42"


def test_build_message_link_basic_group_without_username_returns_none():
    assert build_message_link(-123456789, 42, None) is None


def test_checkme_line_escapes_and_links():
    line = checkme_line(1, "Настолки <3", dt.date(2026, 8, 22), "Компания А & Ко", "https://t.me/c/1/2")
    assert line == (
        '1. <a href="https://t.me/c/1/2">22 августа, Настолки &lt;3</a> (Компания А &amp; Ко)'
    )


def test_checkme_header_escapes():
    assert checkme_header("Alice & Bob") == "Alice &amp; Bob, вы записаны:"


def test_checkme_empty_text_escapes():
    assert checkme_empty_text("Alice & Bob") == "Alice &amp; Bob, у вас нет записей на игры."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatting.py -v`
Expected: the six new tests FAIL with `ImportError` (names not yet defined in `bot.formatting`).

- [ ] **Step 3: Implement the helpers**

In `bot/formatting.py`, add `import html`, alphabetized alongside the existing `import datetime as dt`:

```python
from __future__ import annotations

import datetime as dt
import html

from bot.date_utils import format_date_ru
```

Then append at the end of the file:

```python
def build_message_link(chat_id: int, message_id: int, username: str | None) -> str | None:
    if username:
        return f"https://t.me/{username}/{message_id}"
    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"
    return None


def checkme_line(
    index: int, option_text: str, option_date: dt.date, chat_title: str, link: str
) -> str:
    label = f"{format_date_ru(option_date)}, {html.escape(option_text)}"
    return f'{index}. <a href="{html.escape(link)}">{label}</a> ({html.escape(chat_title)})'


def checkme_header(mention: str) -> str:
    return f"{html.escape(mention)}, вы записаны:"


def checkme_empty_text(mention: str) -> str:
    return f"{html.escape(mention)}, у вас нет записей на игры."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatting.py -v`
Expected: PASS (all tests in the file, old and new).

- [ ] **Step 5: Commit**

```bash
git add bot/formatting.py tests/test_formatting.py
git commit -m "feat: add message-link and checkme text formatting helpers"
```

---

### Task 3: `/checkme` handler

**Files:**
- Create: `bot/handlers/checkme.py`
- Test: Create `tests/test_handlers_checkme.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_handlers_checkme.py`:

```python
import datetime as dt
from unittest.mock import AsyncMock

from bot import repo
from bot.handlers.checkme import handle_checkme


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


async def test_handle_checkme_lists_dated_votes_across_chats_ordered_by_date(session_maker):
    async with session_maker() as session:
        poll_a = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Позже", dt.date(2026, 9, 1))]
        )
        await repo.set_poll_message(session, poll_a.id, message_id=11)
        poll_b = await repo.create_poll(
            session, chat_id=-100200, title="Игра Б", options=[("Раньше", dt.date(2026, 8, 1))]
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

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "@alice, вы записаны:\n"
        '1. <a href="https://t.me/c/200/22">1 августа, Раньше</a> (Компания Б)\n'
        '2. <a href="https://t.me/companya/11">1 сентября, Позже</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_checkme_skips_row_when_get_chat_raises(session_maker):
    async with session_maker() as session:
        poll_ok = await repo.create_poll(
            session, chat_id=100, title="Игра А", options=[("Ок", dt.date(2026, 8, 1))]
        )
        await repo.set_poll_message(session, poll_ok.id, message_id=11)
        poll_broken = await repo.create_poll(
            session, chat_id=200, title="Игра Б", options=[("Недоступно", dt.date(2026, 8, 2))]
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

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "@alice, вы записаны:\n"
        '1. <a href="https://t.me/companya/11">1 августа, Ок</a> (Компания А)',
        parse_mode="HTML",
    )


async def test_handle_checkme_skips_row_when_no_link_possible(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=-123456789, title="Обычная группа", options=[("Вариант", dt.date(2026, 8, 1))]
        )
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Обычная группа", username=None)
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "@alice, у вас нет записей на игры.", parse_mode="HTML"
    )


async def test_handle_checkme_with_no_votes_sends_empty_text(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username=None, first_name="Alice"))

    await handle_checkme(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "Alice, у вас нет записей на игры.", parse_mode="HTML"
    )
    fake_bot.get_chat.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_handlers_checkme.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.checkme'`.

- [ ] **Step 3: Implement the handler**

Create `bot/handlers/checkme.py`:

```python
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot import formatting, repo

router = Router(name="checkme")


@router.message(Command("checkme"))
async def handle_checkme(message: Message, bot: Bot, session_maker) -> None:
    user = message.from_user
    if user is None:
        return

    async with session_maker() as session:
        rows = await repo.get_votes_by_user(session, user.id)

    mention = formatting.voter_mention(user.username, user.first_name)

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

        lines.append(formatting.checkme_line(len(lines) + 1, option.text, option.date, chat.title, link))

    if not lines:
        await message.answer(formatting.checkme_empty_text(mention), parse_mode="HTML")
        return

    text = formatting.checkme_header(mention) + "\n" + "\n".join(lines)
    await message.answer(text, parse_mode="HTML")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_handlers_checkme.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/checkme.py tests/test_handlers_checkme.py
git commit -m "feat: add /checkme handler"
```

---

### Task 4: Register the router

**Files:**
- Modify: `bot/main.py:48` (import line) and `bot/main.py:85` (router registration)

- [ ] **Step 1: Update the import**

In `bot/main.py`, change line 48 from:

```python
from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, dialog_control, voting
```

to:

```python
from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, checkme, dialog_control, voting
```

- [ ] **Step 2: Register the router**

In `bot/main.py`, after line 85 (`dp.include_router(voting.router)`), add:

```python
    dp.include_router(checkme.router)
```

The full block (lines 80-86) should read:

```python
    dp.include_router(dialog_control.router)
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(admin_copy.router)
    dp.include_router(admin_delete.router)
    dp.include_router(voting.router)
    dp.include_router(checkme.router)
```

- [ ] **Step 3: Verify the whole suite still passes**

Run: `pytest -v`
Expected: all tests PASS, including everything from Tasks 1-3.

- [ ] **Step 4: Verify the module imports cleanly**

Run: `python -c "import bot.main"`
Expected: no output, exit code 0 (confirms the new import/registration lines have no syntax or name errors; `bot.main` doesn't execute `main()` on import).

- [ ] **Step 5: Commit**

```bash
git add bot/main.py
git commit -m "feat: register /checkme router"
```

---

## Self-Review Notes

- **Spec coverage:** repo query (Task 1) — done; link-building + HTML escaping (Task 2) — done; handler flow incl. skip-on-failure/no-link/no-date/orphaned-included/dateless-excluded (Task 3) — done; router registration (Task 4) — done. Pagination is explicitly out of scope per the spec.
- **Type consistency:** `get_votes_by_user` returns `list[tuple[Poll, Option]]` in Task 1; Task 3's handler unpacks `for poll, option in rows` — consistent. `build_message_link(chat_id, message_id, username)` signature in Task 2 matches the call site in Task 3. `checkme_line(index, option_text, option_date, chat_title, link)` matches its call site.
- **Orphaned polls:** no separate handling needed — `get_votes_by_user` doesn't filter on `Poll.status`, so `orphaned` polls flow through exactly like `active` ones, matching the spec.
