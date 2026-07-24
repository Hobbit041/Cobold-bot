# Telegram Poll Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that lets one admin run date-poll votes in a chat, with automatic threshold notifications, edit notifications, and day-before reminders, per `docs/superpowers/specs/2026-07-24-poll-bot-design.md`.

**Architecture:** aiogram 3 bot (long polling) backed by SQLite via async SQLAlchemy for poll/vote state, and APScheduler (SQLAlchemy job store) for the 15-minute threshold debounce and the daily reminder cron job. Business logic (vote counting, threshold decisions, message formatting) lives in plain, DB-agnostic modules that are unit-tested directly; aiogram handlers are thin glue that call into those modules.

**Tech Stack:** Python 3.12, aiogram 3.15, SQLAlchemy 2.0 (async, `aiosqlite`), APScheduler 3.10, pytest + pytest-asyncio.

---

## File Structure

```
Botopros/
  requirements.txt
  requirements-dev.txt
  pyproject.toml
  .env.example
  .gitignore
  README.md
  bot/
    __init__.py
    config.py               # env-based Config dataclass
    date_utils.py            # date parsing/formatting (ДД.ММ[.ГГГГ] <-> date)
    models.py                 # SQLAlchemy models: Poll, Option, Vote, ThresholdState, Reminder
    db.py                     # async engine/session factory + init_db
    repo.py                   # all DB read/write operations (business data layer)
    threshold_logic.py        # pure decision functions for the 4-vote debounce
    formatting.py              # pure functions building all outgoing message text
    keyboards.py               # inline keyboard builder
    scheduler.py                # APScheduler wrapper (create/schedule/cancel jobs)
    jobs.py                      # scheduled job callbacks (threshold check, daily reminder)
    main.py                       # entrypoint: wires bot, dispatcher, scheduler, routers
    handlers/
      __init__.py
      voting.py                    # vote toggle callback handler
      admin_create.py               # /newpoll FSM
      admin_edit.py                  # /editpoll FSM
  tests/
    conftest.py
    test_config.py
    test_date_utils.py
    test_db.py
    test_repo_poll.py
    test_repo_voting.py
    test_repo_edit.py
    test_repo_threshold_reminder.py
    test_threshold_logic.py
    test_formatting.py
    test_keyboards.py
    test_scheduler.py
    test_jobs.py
    test_handlers_voting.py
    test_handlers_admin_create.py
    test_handlers_admin_edit.py
  deploy/
    botopros.service
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `bot/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
aiogram==3.15.0
SQLAlchemy==2.0.36
aiosqlite==0.20.0
APScheduler==3.10.4
python-dotenv==1.0.1
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: Create `.env.example`**

```
BOT_TOKEN=123456:ABC-DEF...
ADMIN_ID=123456789
ADMIN_USERNAME=your_username
BOT_TIMEZONE=Europe/Moscow
REMINDER_TIME=19:00
DB_PATH=poll_bot.sqlite3
JOBS_DB_PATH=jobs.sqlite3
```

- [ ] **Step 5: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
*.sqlite3
.env
```

- [ ] **Step 6: Create empty `bot/__init__.py`**

Empty file (just makes `bot` a package).

- [ ] **Step 7: Create venv and install dev dependencies**

Run:
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements-dev.txt
```
Expected: install completes with no errors.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml .env.example .gitignore bot/__init__.py
git commit -m "chore: scaffold Telegram poll bot project"
```

---

### Task 2: Config module

**Files:**
- Create: `bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest

from bot.config import load_config


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("BOT_TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("REMINDER_TIME", "19:00")
    monkeypatch.setenv("DB_PATH", "test.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "test_jobs.sqlite3")

    config = load_config()

    assert config.bot_token == "test-token"
    assert config.admin_id == 42
    assert config.admin_username == "admin_user"
    assert config.timezone.key == "Europe/Moscow"
    assert config.reminder_hour == 19
    assert config.reminder_minute == 0
    assert config.db_path == "test.sqlite3"
    assert config.jobs_db_path == "test_jobs.sqlite3"


def test_load_config_missing_token_raises(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")

    with pytest.raises(KeyError):
        load_config()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 3: Write the implementation**

```python
# bot/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    admin_username: str
    timezone: ZoneInfo
    reminder_hour: int
    reminder_minute: int
    db_path: str
    jobs_db_path: str


def load_config() -> Config:
    bot_token = os.environ["BOT_TOKEN"]
    admin_id = int(os.environ["ADMIN_ID"])
    admin_username = os.environ["ADMIN_USERNAME"]
    timezone = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Europe/Moscow"))

    reminder_time = os.environ.get("REMINDER_TIME", "19:00")
    hour_str, minute_str = reminder_time.split(":")

    db_path = os.environ.get("DB_PATH", "poll_bot.sqlite3")
    jobs_db_path = os.environ.get("JOBS_DB_PATH", "jobs.sqlite3")

    return Config(
        bot_token=bot_token,
        admin_id=admin_id,
        admin_username=admin_username,
        timezone=timezone,
        reminder_hour=int(hour_str),
        reminder_minute=int(minute_str),
        db_path=db_path,
        jobs_db_path=jobs_db_path,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat: add env-based bot config loader"
```

---

### Task 3: Date utilities

**Files:**
- Create: `bot/date_utils.py`
- Test: `tests/test_date_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_date_utils.py
import datetime as dt

import pytest

from bot.date_utils import DateParseError, format_date_ru, parse_date_input


def test_parse_full_date():
    assert parse_date_input("24.07.2026") == dt.date(2026, 7, 24)


def test_parse_two_digit_year():
    assert parse_date_input("24.07.26") == dt.date(2026, 7, 24)


def test_parse_date_without_year_uses_today_year():
    result = parse_date_input("24.07", today=dt.date(2026, 1, 1))
    assert result == dt.date(2026, 7, 24)


def test_parse_invalid_format_raises():
    with pytest.raises(DateParseError):
        parse_date_input("not-a-date")


def test_parse_invalid_calendar_date_raises():
    with pytest.raises(DateParseError):
        parse_date_input("32.13.2026")


def test_format_date_ru():
    assert format_date_ru(dt.date(2026, 7, 24)) == "24 июля"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_date_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.date_utils'`

- [ ] **Step 3: Write the implementation**

```python
# bot/date_utils.py
from __future__ import annotations

import datetime as dt

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


class DateParseError(ValueError):
    pass


def parse_date_input(text: str, today: dt.date | None = None) -> dt.date:
    text = text.strip()
    today = today or dt.date.today()
    parts = text.split(".")

    if len(parts) == 2:
        day_str, month_str = parts
        year = today.year
    elif len(parts) == 3:
        day_str, month_str, year_str = parts
        year = 2000 + int(year_str) if len(year_str) == 2 else int(year_str)
    else:
        raise DateParseError(
            f"Не удалось разобрать дату: {text!r}. Используйте формат ДД.ММ или ДД.ММ.ГГГГ"
        )

    try:
        day = int(day_str)
        month = int(month_str)
        return dt.date(year, month, day)
    except ValueError as exc:
        raise DateParseError(
            f"Не удалось разобрать дату: {text!r}. Используйте формат ДД.ММ или ДД.ММ.ГГГГ"
        ) from exc


def format_date_ru(d: dt.date) -> str:
    return f"{d.day} {MONTHS_RU[d.month]}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_date_utils.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/date_utils.py tests/test_date_utils.py
git commit -m "feat: add Russian date parsing and formatting utilities"
```

---

### Task 4: Models, DB setup, and shared test fixture

**Files:**
- Create: `bot/models.py`
- Create: `bot/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import datetime as dt

from bot.models import Option, Poll


async def test_create_and_query_poll(session_maker):
    async with session_maker() as session:
        poll = Poll(chat_id=100, title="Игра в апреле", status="active")
        option = Option(text="24.07", date=dt.date(2026, 7, 24), position=0, poll=poll)
        session.add(poll)
        session.add(option)
        await session.commit()

        assert poll.id is not None
        assert option.poll_id == poll.id
```

- [ ] **Step 2: Create the shared `session_maker` fixture**

```python
# tests/conftest.py
import pytest_asyncio

from bot.db import create_engine_and_sessionmaker, init_db


@pytest_asyncio.fixture
async def session_maker(tmp_path):
    engine, maker = create_engine_and_sessionmaker(str(tmp_path / "test.sqlite3"))
    await init_db(engine)
    yield maker
    await engine.dispose()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.models'`

- [ ] **Step 4: Write `bot/models.py`**

```python
# bot/models.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int]
    message_id: Mapped[int | None] = mapped_column(default=None)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    options: Mapped[list["Option"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id"))
    text: Mapped[str]
    date: Mapped[dt.date]
    position: Mapped[int]
    is_deleted: Mapped[bool] = mapped_column(default=False)

    poll: Mapped["Poll"] = relationship(back_populates="options")
    votes: Mapped[list["Vote"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )
    threshold_state: Mapped["ThresholdState"] = relationship(
        back_populates="option", cascade="all, delete-orphan", uselist=False
    )
    reminder: Mapped["Reminder"] = relationship(
        back_populates="option", cascade="all, delete-orphan", uselist=False
    )


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("option_id", "user_id", name="uq_vote_option_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"))
    user_id: Mapped[int]
    username: Mapped[str | None]
    first_name: Mapped[str]
    voted_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    option: Mapped["Option"] = relationship(back_populates="votes")


class ThresholdState(Base):
    __tablename__ = "threshold_states"

    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"), primary_key=True)
    announced: Mapped[bool] = mapped_column(default=False)

    option: Mapped["Option"] = relationship(back_populates="threshold_state")


class Reminder(Base):
    __tablename__ = "reminders"

    option_id: Mapped[int] = mapped_column(ForeignKey("options.id"), primary_key=True)
    sent: Mapped[bool] = mapped_column(default=False)

    option: Mapped["Option"] = relationship(back_populates="reminder")
```

- [ ] **Step 5: Write `bot/db.py`**

```python
# bot/db.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.models import Base


def create_engine_and_sessionmaker(
    db_path: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_maker


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_db.py -v`
Expected: PASS (1 test)

- [ ] **Step 7: Commit**

```bash
git add bot/models.py bot/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: add SQLAlchemy models and async DB setup"
```

---

### Task 5: Repo — poll creation and retrieval

**Files:**
- Create: `bot/repo.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_repo_poll.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_poll.py
import datetime as dt

from bot import repo


async def test_create_poll_creates_options_with_state(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )

        options = await repo.get_poll_options(session, poll.id)

        assert [o.text for o in options] == ["24.07", "25.07"]
        assert options[0].position == 0
        assert options[1].position == 1


async def test_set_poll_message_stores_message_id(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=555)

        stored = await repo.get_poll(session, poll.id)
        assert stored.message_id == 555
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_poll.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.repo'`

- [ ] **Step 3: Write the implementation**

```python
# bot/repo.py
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Option, Poll, Reminder, ThresholdState, Vote


async def create_poll(
    session: AsyncSession,
    chat_id: int,
    title: str,
    options: list[tuple[str, dt.date]],
) -> Poll:
    poll = Poll(chat_id=chat_id, title=title, status="active")
    session.add(poll)
    await session.flush()

    for position, (text, option_date) in enumerate(options):
        option = Option(poll_id=poll.id, text=text, date=option_date, position=position)
        session.add(option)
        await session.flush()
        session.add(ThresholdState(option_id=option.id, announced=False))
        session.add(Reminder(option_id=option.id, sent=False))

    await session.commit()
    await session.refresh(poll)
    return poll


async def set_poll_message(session: AsyncSession, poll_id: int, message_id: int) -> None:
    poll = await session.get(Poll, poll_id)
    poll.message_id = message_id
    await session.commit()


async def get_poll_options(session: AsyncSession, poll_id: int) -> list[Option]:
    result = await session.execute(
        select(Option)
        .where(Option.poll_id == poll_id, Option.is_deleted.is_(False))
        .order_by(Option.position)
    )
    return list(result.scalars().all())


async def get_poll(session: AsyncSession, poll_id: int) -> Poll | None:
    return await session.get(Poll, poll_id)
```

- [ ] **Step 4: Add the shared `poll_and_option` fixture**

```python
# tests/conftest.py — append below the existing session_maker fixture
import datetime as dt

from bot import repo


@pytest_asyncio.fixture
async def poll_and_option(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=1, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        options = await repo.get_poll_options(session, poll.id)
        return poll.id, options[0].id
```

- [ ] **Step 5: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_poll.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add bot/repo.py tests/conftest.py tests/test_repo_poll.py
git commit -m "feat: add repo layer for poll creation and retrieval"
```

---

### Task 6: Repo — voting

**Files:**
- Modify: `bot/repo.py`
- Test: `tests/test_repo_voting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_voting.py
from bot import repo


async def test_toggle_vote_adds_then_removes(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        voted_now, count = await repo.toggle_vote(
            session, option_id, user_id=10, username="alice", first_name="Alice"
        )
        assert (voted_now, count) == (True, 1)

        voted_now, count = await repo.toggle_vote(
            session, option_id, user_id=10, username="alice", first_name="Alice"
        )
        assert (voted_now, count) == (False, 0)


async def test_toggle_vote_counts_multiple_users(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        await repo.toggle_vote(session, option_id, user_id=10, username="alice", first_name="Alice")
        await repo.toggle_vote(session, option_id, user_id=11, username=None, first_name="Bob")

        voters = await repo.get_voters(session, option_id)
        assert {v.user_id for v in voters} == {10, 11}
        assert await repo.get_vote_count(session, option_id) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_voting.py -v`
Expected: FAIL with `AttributeError: module 'bot.repo' has no attribute 'toggle_vote'`

- [ ] **Step 3: Add voting functions to `bot/repo.py`**

```python
# bot/repo.py — append

async def toggle_vote(
    session: AsyncSession,
    option_id: int,
    user_id: int,
    username: str | None,
    first_name: str,
) -> tuple[bool, int]:
    result = await session.execute(
        select(Vote).where(Vote.option_id == option_id, Vote.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        await session.delete(existing)
        voted_now = False
    else:
        session.add(Vote(option_id=option_id, user_id=user_id, username=username, first_name=first_name))
        voted_now = True

    await session.commit()
    count = await get_vote_count(session, option_id)
    return voted_now, count


async def get_vote_count(session: AsyncSession, option_id: int) -> int:
    result = await session.execute(select(Vote).where(Vote.option_id == option_id))
    return len(result.scalars().all())


async def get_voters(session: AsyncSession, option_id: int) -> list[Vote]:
    result = await session.execute(
        select(Vote).where(Vote.option_id == option_id).order_by(Vote.voted_at)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_voting.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_voting.py
git commit -m "feat: add vote toggle and vote query functions to repo"
```

---

### Task 7: Repo — edit and delete option

**Files:**
- Modify: `bot/repo.py`
- Test: `tests/test_repo_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_edit.py
import datetime as dt

from bot import repo


async def test_edit_option_text(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        updated = await repo.edit_option_text(session, option_id, "25.07 вместо 24.07")
        assert updated.text == "25.07 вместо 24.07"


async def test_edit_option_date(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        updated = await repo.edit_option_date(session, option_id, dt.date(2026, 8, 1))
        assert updated.date == dt.date(2026, 8, 1)


async def test_delete_option_removes_votes_and_marks_deleted(session_maker, poll_and_option):
    poll_id, option_id = poll_and_option
    async with session_maker() as session:
        await repo.toggle_vote(session, option_id, user_id=10, username="alice", first_name="Alice")
        await repo.delete_option(session, option_id)

        remaining_options = await repo.get_poll_options(session, poll_id)
        assert remaining_options == []
        assert await repo.get_vote_count(session, option_id) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_edit.py -v`
Expected: FAIL with `AttributeError: module 'bot.repo' has no attribute 'edit_option_text'`

- [ ] **Step 3: Add edit/delete functions to `bot/repo.py`**

```python
# bot/repo.py — append

async def edit_option_text(session: AsyncSession, option_id: int, new_text: str) -> Option:
    option = await session.get(Option, option_id)
    option.text = new_text
    await session.commit()
    await session.refresh(option)
    return option


async def edit_option_date(session: AsyncSession, option_id: int, new_date: dt.date) -> Option:
    option = await session.get(Option, option_id)
    option.date = new_date
    await session.commit()
    await session.refresh(option)
    return option


async def delete_option(session: AsyncSession, option_id: int) -> None:
    votes = await get_voters(session, option_id)
    for vote in votes:
        await session.delete(vote)

    option = await session.get(Option, option_id)
    option.is_deleted = True

    threshold_state = await session.get(ThresholdState, option_id)
    if threshold_state:
        await session.delete(threshold_state)

    reminder = await session.get(Reminder, option_id)
    if reminder:
        await session.delete(reminder)

    await session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_edit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_edit.py
git commit -m "feat: add option text/date edit and soft-delete to repo"
```

---

### Task 8: Repo — threshold and reminder state

**Files:**
- Modify: `bot/repo.py`
- Test: `tests/test_repo_threshold_reminder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_threshold_reminder.py
import datetime as dt

from bot import repo


async def test_announced_defaults_false_and_can_be_set(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        assert await repo.is_announced(session, option_id) is False

        await repo.set_announced(session, option_id, True)
        assert await repo.is_announced(session, option_id) is True


async def test_reminder_sent_defaults_false_and_can_be_set(session_maker, poll_and_option):
    _, option_id = poll_and_option
    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, option_id) is False

        await repo.set_reminder_sent(session, option_id, True)
        assert await repo.is_reminder_sent(session, option_id) is True


async def test_get_options_due_for_reminder_filters_correctly(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=1,
            title="Игра",
            options=[
                ("Вариант A", dt.date(2026, 7, 25)),
                ("Вариант B", dt.date(2026, 7, 25)),
                ("Вариант C", dt.date(2026, 7, 26)),
            ],
        )
        options = await repo.get_poll_options(session, poll.id)
        option_a, option_b, option_c = options

        await repo.set_announced(session, option_a.id, True)
        await repo.set_announced(session, option_b.id, True)
        await repo.set_reminder_sent(session, option_b.id, True)
        await repo.set_announced(session, option_c.id, True)

        due = await repo.get_options_due_for_reminder(session, dt.date(2026, 7, 25))

        assert [o.id for o in due] == [option_a.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_threshold_reminder.py -v`
Expected: FAIL with `AttributeError: module 'bot.repo' has no attribute 'is_announced'`

- [ ] **Step 3: Add threshold/reminder functions to `bot/repo.py`**

```python
# bot/repo.py — append

async def is_announced(session: AsyncSession, option_id: int) -> bool:
    state = await session.get(ThresholdState, option_id)
    return bool(state and state.announced)


async def set_announced(session: AsyncSession, option_id: int, value: bool) -> None:
    state = await session.get(ThresholdState, option_id)
    state.announced = value
    await session.commit()


async def is_reminder_sent(session: AsyncSession, option_id: int) -> bool:
    reminder = await session.get(Reminder, option_id)
    return bool(reminder and reminder.sent)


async def set_reminder_sent(session: AsyncSession, option_id: int, value: bool) -> None:
    reminder = await session.get(Reminder, option_id)
    reminder.sent = value
    await session.commit()


async def get_options_due_for_reminder(session: AsyncSession, target_date: dt.date) -> list[Option]:
    result = await session.execute(
        select(Option)
        .join(ThresholdState, ThresholdState.option_id == Option.id)
        .join(Reminder, Reminder.option_id == Option.id)
        .where(
            Option.date == target_date,
            Option.is_deleted.is_(False),
            ThresholdState.announced.is_(True),
            Reminder.sent.is_(False),
        )
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_repo_threshold_reminder.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_threshold_reminder.py
git commit -m "feat: add threshold and reminder state tracking to repo"
```

---

### Task 9: Threshold decision logic (pure)

**Files:**
- Create: `bot/threshold_logic.py`
- Test: `tests/test_threshold_logic.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_threshold_logic.py
from bot.threshold_logic import (
    ANNOUNCE_DROP,
    CANCEL_TIMER,
    NO_ACTION,
    SCHEDULE_TIMER,
    decide_action_after_vote_change,
    should_announce_on_timer_fire,
)


def test_not_announced_reaching_threshold_schedules_timer():
    assert decide_action_after_vote_change(new_count=4, announced=False) == SCHEDULE_TIMER


def test_not_announced_below_threshold_cancels_timer():
    assert decide_action_after_vote_change(new_count=3, announced=False) == CANCEL_TIMER


def test_announced_dropping_below_threshold_announces_drop():
    assert decide_action_after_vote_change(new_count=3, announced=True) == ANNOUNCE_DROP


def test_announced_staying_above_threshold_no_action():
    assert decide_action_after_vote_change(new_count=5, announced=True) == NO_ACTION


def test_should_announce_on_timer_fire_true_when_still_at_threshold():
    assert should_announce_on_timer_fire(4) is True


def test_should_announce_on_timer_fire_false_when_dropped():
    assert should_announce_on_timer_fire(3) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_threshold_logic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.threshold_logic'`

- [ ] **Step 3: Write the implementation**

```python
# bot/threshold_logic.py
DEFAULT_THRESHOLD = 4

SCHEDULE_TIMER = "schedule_or_reschedule_timer"
CANCEL_TIMER = "cancel_timer"
ANNOUNCE_DROP = "announce_drop"
NO_ACTION = "no_action"


def decide_action_after_vote_change(
    new_count: int, announced: bool, threshold: int = DEFAULT_THRESHOLD
) -> str:
    if not announced and new_count >= threshold:
        return SCHEDULE_TIMER
    if not announced and new_count < threshold:
        return CANCEL_TIMER
    if announced and new_count < threshold:
        return ANNOUNCE_DROP
    return NO_ACTION


def should_announce_on_timer_fire(current_count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    return current_count >= threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_threshold_logic.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/threshold_logic.py tests/test_threshold_logic.py
git commit -m "feat: add pure decision logic for 4-vote threshold debounce"
```

---

### Task 10: Message formatting

**Files:**
- Create: `bot/formatting.py`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_formatting.py
import datetime as dt

from bot.formatting import (
    option_date_changed_notification,
    option_deleted_notification,
    option_text_changed_notification,
    poll_message_text,
    reminder_text,
    threshold_dropped_text,
    threshold_reached_text,
    voter_mention,
)


def test_voter_mention_with_username():
    assert voter_mention("alice", "Alice") == "@alice"


def test_voter_mention_without_username_falls_back_to_first_name():
    assert voter_mention(None, "Bob") == "Bob"


def test_poll_message_text_joins_lines():
    text = poll_message_text("Игра в апреле", ["1. 24.07 — 2 🗳", "2. 25.07 — 0 🗳"])
    assert text == "📅 Игра в апреле\n\n1. 24.07 — 2 🗳\n2. 25.07 — 0 🗳"


def test_threshold_reached_text():
    text = threshold_reached_text("@admin", "24.07")
    assert text == "@admin, за вариант «24.07» проголосовало 4 человека!"


def test_threshold_dropped_text():
    text = threshold_dropped_text("24.07")
    assert text == "За вариант «24.07» снова меньше 4х человек. Проголосуйте, а то игра отменится!"


def test_option_deleted_notification_lists_voters():
    text = option_deleted_notification("24.07", ["@alice", "Bob"])
    assert text == (
        "@alice, Bob, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24.07» удалён."
    )


def test_option_deleted_notification_without_voters():
    text = option_deleted_notification("24.07", [])
    assert text == "вы проголосовали за вариант, но он изменился! В опрос внесены изменения: вариант «24.07» удалён."


def test_option_text_changed_notification():
    text = option_text_changed_notification("24.07", "24.07 (уточнено время)", ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24.07» → «24.07 (уточнено время)»."
    )


def test_option_date_changed_notification():
    text = option_date_changed_notification("Игра", dt.date(2026, 7, 24), dt.date(2026, 7, 26), ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «Игра» перенесён с 24 июля на 26 июля."
    )


def test_reminder_text_lists_participants():
    text = reminder_text(dt.date(2026, 7, 25), ["@alice", "Bob"])
    assert text == (
        "Напоминаю, что завтра, 25 июля, состоится игра! "
        "Пожалуйста, подтвердите участие реакцией на это сообщение:\n@alice\nBob"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.formatting'`

- [ ] **Step 3: Write the implementation**

```python
# bot/formatting.py
from __future__ import annotations

import datetime as dt

from bot.date_utils import format_date_ru


def voter_mention(username: str | None, first_name: str) -> str:
    if username:
        return f"@{username}"
    return first_name


def format_option_line(index: int, option_text: str, option_date: dt.date, vote_count: int) -> str:
    return f"{index}. {option_text} ({format_date_ru(option_date)}) — {vote_count} 🗳"


def poll_message_text(title: str, option_lines: list[str]) -> str:
    body = "\n".join(option_lines)
    return f"📅 {title}\n\n{body}"


def threshold_reached_text(admin_mention: str, option_text: str) -> str:
    return f"{admin_mention}, за вариант «{option_text}» проголосовало 4 человека!"


def threshold_dropped_text(option_text: str) -> str:
    return f"За вариант «{option_text}» снова меньше 4х человек. Проголосуйте, а то игра отменится!"


def option_deleted_notification(option_text: str, voter_mentions: list[str]) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: вариант «{option_text}» удалён."
    )


def option_text_changed_notification(old_text: str, new_text: str, voter_mentions: list[str]) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{old_text}» → «{new_text}»."
    )


def option_date_changed_notification(
    option_text: str, old_date: dt.date, new_date: dt.date, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{option_text}» перенесён с {format_date_ru(old_date)} "
        f"на {format_date_ru(new_date)}."
    )


def reminder_text(option_date: dt.date, participant_mentions: list[str]) -> str:
    participants_block = "\n".join(participant_mentions)
    return (
        f"Напоминаю, что завтра, {format_date_ru(option_date)}, состоится игра! "
        f"Пожалуйста, подтвердите участие реакцией на это сообщение:\n{participants_block}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_formatting.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/formatting.py tests/test_formatting.py
git commit -m "feat: add pure message formatting functions"
```

---

### Task 11: Inline keyboard builder

**Files:**
- Create: `bot/keyboards.py`
- Test: `tests/test_keyboards.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keyboards.py
from bot.keyboards import build_poll_keyboard


def test_build_poll_keyboard_creates_one_button_per_option():
    markup = build_poll_keyboard([(1, "24.07", 2), (2, "25.07", 0)])

    rows = markup.inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].text == "24.07 (2)"
    assert rows[0][0].callback_data == "vote:1"
    assert rows[1][0].text == "25.07 (0)"
    assert rows[1][0].callback_data == "vote:2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_keyboards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.keyboards'`

- [ ] **Step 3: Write the implementation**

```python
# bot/keyboards.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_poll_keyboard(options: list[tuple[int, str, int]]) -> InlineKeyboardMarkup:
    """options: list of (option_id, text, vote_count)."""
    builder = InlineKeyboardBuilder()
    for option_id, text, vote_count in options:
        builder.button(text=f"{text} ({vote_count})", callback_data=f"vote:{option_id}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_keyboards.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add bot/keyboards.py tests/test_keyboards.py
git commit -m "feat: add poll inline keyboard builder"
```

---

### Task 12: Scheduler wrapper

**Files:**
- Create: `bot/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler.py
from zoneinfo import ZoneInfo

from bot.scheduler import (
    cancel_threshold_check,
    create_scheduler,
    schedule_daily_reminder_job,
    schedule_threshold_check,
    threshold_job_id,
)


def _noop(option_id):
    pass


def test_schedule_threshold_check_creates_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_minutes=15)

    job = scheduler.get_job(threshold_job_id(1))
    assert job is not None


def test_schedule_threshold_check_replaces_existing_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_minutes=15)
    first_run_time = scheduler.get_job(threshold_job_id(1)).next_run_time

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_minutes=20)
    second_run_time = scheduler.get_job(threshold_job_id(1)).next_run_time

    assert len(scheduler.get_jobs()) == 1
    assert second_run_time > first_run_time


def test_cancel_threshold_check_removes_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_minutes=15)

    cancel_threshold_check(scheduler, option_id=1)

    assert scheduler.get_job(threshold_job_id(1)) is None


def test_cancel_threshold_check_noop_when_no_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    cancel_threshold_check(scheduler, option_id=999)


def test_schedule_daily_reminder_job_creates_cron_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_daily_reminder_job(scheduler, callback=_noop, hour=19, minute=0)

    job = scheduler.get_job("daily_reminder_check")
    assert job is not None
```

Note: `_noop` must stay a module-level function (not a lambda or closure) — `SQLAlchemyJobStore` pickles job references by qualified name.

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.scheduler'`

- [ ] **Step 3: Write the implementation**

```python
# bot/scheduler.py
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger


def create_scheduler(jobs_db_path: str, timezone: ZoneInfo) -> AsyncIOScheduler:
    jobstore = SQLAlchemyJobStore(url=f"sqlite:///{jobs_db_path}")
    return AsyncIOScheduler(jobstores={"default": jobstore}, timezone=timezone)


def threshold_job_id(option_id: int) -> str:
    return f"threshold_check:{option_id}"


def schedule_threshold_check(
    scheduler: AsyncIOScheduler, option_id: int, callback, delay_minutes: int = 15
) -> None:
    run_date = dt.datetime.now(scheduler.timezone) + dt.timedelta(minutes=delay_minutes)
    scheduler.add_job(
        callback,
        trigger=DateTrigger(run_date=run_date),
        args=[option_id],
        id=threshold_job_id(option_id),
        replace_existing=True,
    )


def cancel_threshold_check(scheduler: AsyncIOScheduler, option_id: int) -> None:
    job_id = threshold_job_id(option_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def schedule_daily_reminder_job(scheduler: AsyncIOScheduler, callback, hour: int, minute: int) -> None:
    scheduler.add_job(
        callback,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_reminder_check",
        replace_existing=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_scheduler.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/scheduler.py tests/test_scheduler.py
git commit -m "feat: add APScheduler wrapper for threshold debounce and daily reminder"
```

---

### Task 13: Scheduled job callbacks

**Files:**
- Create: `bot/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jobs.py
import datetime as dt
from zoneinfo import ZoneInfo

from bot import jobs, repo


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text):
        self.sent_messages.append((chat_id, text))


async def test_threshold_check_callback_announces_when_still_at_threshold(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"user{user_id}", first_name=f"User{user_id}"
            )

    fake_bot = FakeBot()
    callback = jobs.make_threshold_check_callback(fake_bot, session_maker, admin_mention="@admin")
    await callback(option.id)

    assert fake_bot.sent_messages == [(555, "@admin, за вариант «24.07» проголосовало 4 человека!")]

    async with session_maker() as session:
        assert await repo.is_announced(session, option.id) is True


async def test_threshold_check_callback_skips_when_dropped_below(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="a", first_name="A")

    fake_bot = FakeBot()
    callback = jobs.make_threshold_check_callback(fake_bot, session_maker, admin_mention="@admin")
    await callback(option.id)

    assert fake_bot.sent_messages == []


async def test_daily_reminder_callback_sends_and_marks_sent(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=777, title="Игра", options=[("Игра", tomorrow)])
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")
        await repo.set_announced(session, option.id, True)

    fake_bot = FakeBot()
    callback = jobs.make_daily_reminder_callback(fake_bot, session_maker, tz)
    await callback()

    assert len(fake_bot.sent_messages) == 1
    chat_id, text = fake_bot.sent_messages[0]
    assert chat_id == 777
    assert "@alice" in text

    async with session_maker() as session:
        assert await repo.is_reminder_sent(session, option.id) is True


async def test_daily_reminder_callback_skips_not_announced(session_maker):
    tz = ZoneInfo("Europe/Moscow")
    tomorrow = dt.datetime.now(tz).date() + dt.timedelta(days=1)

    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=777, title="Игра", options=[("Игра", tomorrow)])
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=1, username="alice", first_name="Alice")

    fake_bot = FakeBot()
    callback = jobs.make_daily_reminder_callback(fake_bot, session_maker, tz)
    await callback()

    assert fake_bot.sent_messages == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.jobs'`

- [ ] **Step 3: Write the implementation**

```python
# bot/jobs.py
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from bot import formatting, repo, threshold_logic


def make_threshold_check_callback(bot, session_maker, admin_mention: str):
    async def check_threshold(option_id: int) -> None:
        async with session_maker() as session:
            option = await session.get(repo.Option, option_id)
            if option is None or option.is_deleted:
                return

            count = await repo.get_vote_count(session, option_id)
            if not threshold_logic.should_announce_on_timer_fire(count):
                return

            await repo.set_announced(session, option_id, True)
            poll = await repo.get_poll(session, option.poll_id)
            chat_id = poll.chat_id
            option_text = option.text

        await bot.send_message(
            chat_id=chat_id, text=formatting.threshold_reached_text(admin_mention, option_text)
        )

    return check_threshold


def make_daily_reminder_callback(bot, session_maker, timezone: ZoneInfo):
    async def send_due_reminders() -> None:
        today = dt.datetime.now(timezone).date()
        tomorrow = today + dt.timedelta(days=1)

        async with session_maker() as session:
            due_options = await repo.get_options_due_for_reminder(session, tomorrow)
            to_send = []
            for option in due_options:
                voters = await repo.get_voters(session, option.id)
                mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
                poll = await repo.get_poll(session, option.poll_id)
                to_send.append((poll.chat_id, option.id, option.date, mentions))

            for chat_id, option_id, option_date, mentions in to_send:
                await bot.send_message(chat_id=chat_id, text=formatting.reminder_text(option_date, mentions))
                await repo.set_reminder_sent(session, option_id, True)

    return send_due_reminders
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_jobs.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/jobs.py tests/test_jobs.py
git commit -m "feat: add threshold-check and daily-reminder job callbacks"
```

---

### Task 14: Voting handler

**Files:**
- Create: `bot/handlers/__init__.py`
- Create: `bot/handlers/voting.py`
- Test: `tests/test_handlers_voting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_handlers_voting.py
import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from bot import repo
from bot.handlers.voting import handle_vote_toggle
from bot.scheduler import create_scheduler, threshold_job_id


class FakeUser:
    def __init__(self, id, username, first_name):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeCallback:
    def __init__(self, data, user):
        self.data = data
        self.from_user = user
        self.answer = AsyncMock()


async def _noop_threshold_callback(option_id):
    pass


async def test_handle_vote_toggle_registers_vote_and_updates_keyboard(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=10, username="alice", first_name="Alice"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    async with session_maker() as session:
        assert await repo.get_vote_count(session, option.id) == 1

    fake_bot.edit_message_reply_markup.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Голос учтён!")


async def test_handle_vote_toggle_reaching_threshold_schedules_job(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(3):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"u{user_id}", first_name=f"U{user_id}"
            )

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=99, username="last", first_name="Last"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    assert scheduler.get_job(threshold_job_id(option.id)) is not None


async def test_handle_vote_toggle_dropping_below_threshold_sends_drop_message(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"u{user_id}", first_name=f"U{user_id}"
            )
        await repo.set_announced(session, option.id, True)

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(data=f"vote:{option.id}", user=FakeUser(id=0, username="u0", first_name="U0"))

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100, text="За вариант «24.07» снова меньше 4х человек. Проголосуйте, а то игра отменится!"
    )
    async with session_maker() as session:
        assert await repo.is_announced(session, option.id) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers'`

- [ ] **Step 3: Create empty `bot/handlers/__init__.py`**

Empty file.

- [ ] **Step 4: Write the implementation**

```python
# bot/handlers/voting.py
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot import formatting, keyboards, repo, threshold_logic
from bot.scheduler import cancel_threshold_check, schedule_threshold_check

router = Router(name="voting")


@router.callback_query(F.data.startswith("vote:"))
async def handle_vote_toggle(
    callback: CallbackQuery,
    session_maker,
    scheduler,
    bot: Bot,
    admin_mention: str,
    threshold_check_callback,
) -> None:
    option_id = int(callback.data.split(":", 1)[1])
    user = callback.from_user

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None or option.is_deleted:
            await callback.answer("Этот вариант больше недоступен.", show_alert=True)
            return

        voted_now, new_count = await repo.toggle_vote(
            session, option_id, user_id=user.id, username=user.username, first_name=user.first_name
        )
        announced = await repo.is_announced(session, option_id)
        poll_options = await repo.get_poll_options(session, option.poll_id)
        poll = await repo.get_poll(session, option.poll_id)

        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        option_text = option.text

    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, counts[opt.id]) for opt in poll_options]
    )
    await bot.edit_message_reply_markup(
        chat_id=poll.chat_id, message_id=poll.message_id, reply_markup=keyboard
    )

    action = threshold_logic.decide_action_after_vote_change(new_count, announced)

    if action == threshold_logic.SCHEDULE_TIMER:
        schedule_threshold_check(scheduler, option_id, threshold_check_callback, delay_minutes=15)
    elif action == threshold_logic.CANCEL_TIMER:
        cancel_threshold_check(scheduler, option_id)
    elif action == threshold_logic.ANNOUNCE_DROP:
        async with session_maker() as session:
            await repo.set_announced(session, option_id, False)
        await bot.send_message(chat_id=poll.chat_id, text=formatting.threshold_dropped_text(option_text))

    await callback.answer("Голос учтён!" if voted_now else "Голос снят.")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/__init__.py bot/handlers/voting.py tests/test_handlers_voting.py
git commit -m "feat: add vote toggle handler wired to threshold debounce"
```

---

### Task 15: Admin create-poll handler

**Files:**
- Create: `bot/handlers/admin_create.py`
- Test: `tests/test_handlers_admin_create.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_handlers_admin_create.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_create.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.admin_create'`

- [ ] **Step 3: Write the implementation**

```python
# bot/handlers/admin_create.py
from __future__ import annotations

import datetime as dt

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot import date_utils, formatting, keyboards, repo

router = Router(name="admin_create")


class CreatePollStates(StatesGroup):
    waiting_title = State()
    waiting_options = State()
    waiting_chat = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("newpoll"))
async def start_create_poll(message: Message, state: FSMContext, admin_id: int) -> None:
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда доступна только администратору.")
        return

    await state.set_state(CreatePollStates.waiting_title)
    await state.update_data(options=[])
    await message.answer("Введите название опроса:")


@router.message(CreatePollStates.waiting_title)
async def receive_title(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправьте текстовое название.")
        return

    await state.update_data(title=message.text)
    await state.set_state(CreatePollStates.waiting_options)
    await message.answer(
        "Теперь добавляйте варианты по одному в формате:\n"
        "Текст | ДД.ММ.ГГГГ\n"
        "Когда закончите — отправьте /done"
    )


@router.message(CreatePollStates.waiting_options, Command("done"))
async def finish_options(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    options = data.get("options", [])
    if not options:
        await message.answer("Нужно добавить хотя бы один вариант перед /done.")
        return

    await state.set_state(CreatePollStates.waiting_chat)
    await message.answer("Перешлите любое сообщение из целевого чата, либо пришлите его chat id.")


@router.message(CreatePollStates.waiting_options)
async def receive_option(message: Message, state: FSMContext) -> None:
    if not message.text or "|" not in message.text:
        await message.answer("Формат: Текст | ДД.ММ.ГГГГ. Попробуйте снова.")
        return

    text_part, date_part = message.text.split("|", 1)
    text_part = text_part.strip()
    try:
        parsed_date = date_utils.parse_date_input(date_part.strip())
    except date_utils.DateParseError as exc:
        await message.answer(str(exc))
        return

    data = await state.get_data()
    options = data.get("options", [])
    options.append({"text": text_part, "date": parsed_date.isoformat()})
    await state.update_data(options=options)
    await message.answer(
        f"Добавлено: {text_part} ({date_utils.format_date_ru(parsed_date)}). Ещё вариант или /done."
    )


@router.message(CreatePollStates.waiting_chat)
async def receive_target_chat(message: Message, state: FSMContext, bot: Bot, session_maker) -> None:
    chat_id = None
    forward_origin = getattr(message, "forward_origin", None)
    if forward_origin is not None and hasattr(forward_origin, "chat"):
        chat_id = forward_origin.chat.id
    elif getattr(message, "forward_from_chat", None) is not None:
        chat_id = message.forward_from_chat.id
    elif message.text:
        try:
            chat_id = int(message.text.strip())
        except ValueError:
            chat_id = None

    if chat_id is None:
        await message.answer("Не удалось определить чат. Перешлите сообщение из чата или пришлите его id.")
        return

    data = await state.get_data()
    title = data["title"]
    options = [(opt["text"], dt.date.fromisoformat(opt["date"])) for opt in data["options"]]

    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=chat_id, title=title, options=options)
        poll_options = await repo.get_poll_options(session, poll.id)
        lines = [
            formatting.format_option_line(i + 1, opt.text, opt.date, 0)
            for i, opt in enumerate(poll_options)
        ]
        text = formatting.poll_message_text(title, lines)
        keyboard = keyboards.build_poll_keyboard([(opt.id, opt.text, 0) for opt in poll_options])

        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        await repo.set_poll_message(session, poll.id, sent.message_id)

    await state.clear()
    await message.answer("Опрос создан и опубликован!")
```

Note: verify `message.forward_origin` / `message.forward_from_chat` against the installed aiogram 3.15 `Message` model during manual testing — Bot API forward metadata has changed across API versions, and the code above tries both attribute shapes defensively.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_create.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_create.py tests/test_handlers_admin_create.py
git commit -m "feat: add /newpoll admin creation flow"
```

---

### Task 16: Admin edit-poll handler

**Files:**
- Create: `bot/handlers/admin_edit.py`
- Test: `tests/test_handlers_admin_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_handlers_admin_edit.py
import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot import repo
from bot.handlers.admin_edit import apply_new_text, select_action, select_option, select_poll, start_edit_poll
from bot.scheduler import create_scheduler


class FakeMessage:
    def __init__(self, text, user_id=1):
        self.text = text
        self.from_user = type("U", (), {"id": user_id})()
        self.answer = AsyncMock()


def _state():
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=1, user_id=1)
    return FSMContext(storage=storage, key=key)


async def test_edit_text_notifies_existing_voters(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("24.07", dt.date(2026, 7, 24))]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await repo.toggle_vote(session, option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("text"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )
    await apply_new_text(FakeMessage("24.07 (в 19:00)"), state, bot=fake_bot, session_maker=session_maker)

    fake_bot.edit_message_text.assert_awaited_once()
    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! В опрос внесены изменения: «24.07» → «24.07 (в 19:00)».",
    )

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "24.07 (в 19:00)"


async def test_delete_option_notifies_and_removes_it(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        target_option = options[0]
        await repo.toggle_vote(session, target_option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("delete"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! В опрос внесены изменения: вариант «24.07» удалён.",
    )

    async with session_maker() as session:
        remaining = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in remaining] == ["25.07"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot.handlers.admin_edit'`

- [ ] **Step 3: Write the implementation**

```python
# bot/handlers/admin_edit.py
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot import date_utils, formatting, keyboards, repo
from bot.models import Poll
from bot.scheduler import cancel_threshold_check

router = Router(name="admin_edit")


class EditPollStates(StatesGroup):
    waiting_poll_selection = State()
    waiting_option_selection = State()
    waiting_action = State()
    waiting_new_text = State()
    waiting_new_date = State()


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("editpoll"))
async def start_edit_poll(message: Message, state: FSMContext, admin_id: int, session_maker) -> None:
    if not _is_admin(message, admin_id):
        await message.answer("Эта команда доступна только администратору.")
        return

    async with session_maker() as session:
        result = await session.execute(select(Poll).where(Poll.status == "active"))
        polls = list(result.scalars().all())

    if not polls:
        await message.answer("Активных опросов нет.")
        return

    lines = [f"{i + 1}. {poll.title} (id={poll.id})" for i, poll in enumerate(polls)]
    await state.update_data(poll_ids=[poll.id for poll in polls])
    await state.set_state(EditPollStates.waiting_poll_selection)
    await message.answer("Выберите опрос по номеру:\n" + "\n".join(lines))


@router.message(EditPollStates.waiting_poll_selection)
async def select_poll(message: Message, state: FSMContext, session_maker) -> None:
    data = await state.get_data()
    poll_ids = data["poll_ids"]
    try:
        index = int(message.text.strip()) - 1
        poll_id = poll_ids[index]
    except (ValueError, IndexError, AttributeError):
        await message.answer("Некорректный номер. Попробуйте снова.")
        return

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll_id)

    lines = [f"{i + 1}. {opt.text} ({date_utils.format_date_ru(opt.date)})" for i, opt in enumerate(options)]
    await state.update_data(poll_id=poll_id, option_ids=[opt.id for opt in options])
    await state.set_state(EditPollStates.waiting_option_selection)
    await message.answer("Выберите вариант по номеру:\n" + "\n".join(lines))


@router.message(EditPollStates.waiting_option_selection)
async def select_option(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    option_ids = data["option_ids"]
    try:
        index = int(message.text.strip()) - 1
        option_id = option_ids[index]
    except (ValueError, IndexError, AttributeError):
        await message.answer("Некорректный номер. Попробуйте снова.")
        return

    await state.update_data(option_id=option_id)
    await state.set_state(EditPollStates.waiting_action)
    await message.answer("Что сделать с вариантом? Ответьте: text / date / delete")


@router.message(EditPollStates.waiting_action)
async def select_action(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler) -> None:
    action = (message.text or "").strip().lower()
    data = await state.get_data()
    option_id = data["option_id"]

    if action == "text":
        await state.set_state(EditPollStates.waiting_new_text)
        await message.answer("Введите новый текст варианта:")
        return

    if action == "date":
        await state.set_state(EditPollStates.waiting_new_date)
        await message.answer("Введите новую дату (ДД.ММ.ГГГГ):")
        return

    if action == "delete":
        await _apply_delete(message, state, bot, session_maker, scheduler, option_id)
        return

    await message.answer("Не понял. Ответьте: text / date / delete")


@router.message(EditPollStates.waiting_new_text)
async def apply_new_text(message: Message, state: FSMContext, bot: Bot, session_maker) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправьте текст.")
        return

    data = await state.get_data()
    option_id = data["option_id"]
    new_text = message.text.strip()

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        old_text = option.text
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_text(session, option_id, new_text)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        await bot.send_message(
            chat_id=poll.chat_id, text=formatting.option_text_changed_notification(old_text, new_text, mentions)
        )

    await state.clear()
    await message.answer("Вариант обновлён.")


@router.message(EditPollStates.waiting_new_date)
async def apply_new_date(message: Message, state: FSMContext, bot: Bot, session_maker) -> None:
    if not message.text:
        await message.answer("Пожалуйста, отправьте дату.")
        return

    data = await state.get_data()
    option_id = data["option_id"]

    try:
        new_date = date_utils.parse_date_input(message.text.strip())
    except date_utils.DateParseError as exc:
        await message.answer(str(exc))
        return

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        old_date = option.date
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_date(session, option_id, new_date)
        poll = await repo.get_poll(session, updated.poll_id)
        poll_options = await repo.get_poll_options(session, updated.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        text = formatting.option_date_changed_notification(updated.text, old_date, new_date, mentions)
        await bot.send_message(chat_id=poll.chat_id, text=text)

    await state.clear()
    await message.answer("Дата варианта обновлена.")


async def _apply_delete(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler, option_id: int) -> None:
    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        option_text = option.text
        voters = await repo.get_voters(session, option_id)
        poll = await repo.get_poll(session, option.poll_id)
        await repo.delete_option(session, option_id)
        poll_options = await repo.get_poll_options(session, option.poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}

    cancel_threshold_check(scheduler, option_id)
    await _refresh_poll_message(bot, poll, poll_options, counts)

    if voters:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        await bot.send_message(chat_id=poll.chat_id, text=formatting.option_deleted_notification(option_text, mentions))

    await state.clear()
    await message.answer("Вариант удалён.")


async def _refresh_poll_message(bot: Bot, poll: Poll, poll_options, counts: dict[int, int]) -> None:
    lines = [
        formatting.format_option_line(i + 1, opt.text, opt.date, counts[opt.id])
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard([(opt.id, opt.text, counts[opt.id]) for opt in poll_options])
    await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: add /editpoll admin flow with voter change notifications"
```

---

### Task 17: Main entrypoint

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: Write the implementation**

```python
# bot/main.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.db import create_engine_and_sessionmaker, init_db
from bot.handlers import admin_create, admin_edit, voting
from bot.jobs import make_daily_reminder_callback, make_threshold_check_callback
from bot.scheduler import create_scheduler, schedule_daily_reminder_job


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    engine, session_maker = create_engine_and_sessionmaker(config.db_path)
    await init_db(engine)

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(voting.router)

    scheduler = create_scheduler(config.jobs_db_path, config.timezone)
    admin_mention = f"@{config.admin_username}"

    threshold_check_callback = make_threshold_check_callback(bot, session_maker, admin_mention)
    daily_reminder_callback = make_daily_reminder_callback(bot, session_maker, config.timezone)
    schedule_daily_reminder_job(scheduler, daily_reminder_callback, config.reminder_hour, config.reminder_minute)
    scheduler.start()

    try:
        await dp.start_polling(
            bot,
            session_maker=session_maker,
            scheduler=scheduler,
            admin_mention=admin_mention,
            admin_id=config.admin_id,
            threshold_check_callback=threshold_check_callback,
        )
    finally:
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run: `source .venv/Scripts/activate && python -m pytest -v`
Expected: PASS (all tests from Tasks 2-16)

- [ ] **Step 3: Manual smoke test**

Fill in a real `.env` (copy from `.env.example`) with a test bot token from BotFather and your Telegram id, then run:
```bash
source .venv/Scripts/activate
python -m bot.main
```
Expected: process starts and logs `Start polling` with no exceptions. Stop with Ctrl+C — expected clean shutdown (no traceback).

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat: wire dispatcher, routers, and scheduler in main entrypoint"
```

---

### Task 18: Deployment files and manual scenario walkthrough

**Files:**
- Create: `deploy/botopros.service`
- Create: `README.md`

- [ ] **Step 1: Write the systemd unit file**

```ini
# deploy/botopros.service
[Unit]
Description=Botopros Telegram poll bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/botopros
EnvironmentFile=/opt/botopros/.env
ExecStart=/opt/botopros/.venv/bin/python -m bot.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Botopros — Telegram-бот для голосования по датам

## Локальный запуск

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
cp .env.example .env            # заполните BOT_TOKEN, ADMIN_ID, ADMIN_USERNAME
python -m pytest -v
python -m bot.main
```

## Деплой на VPS (systemd)

```bash
sudo mkdir -p /opt/botopros
sudo chown $USER:$USER /opt/botopros
git clone <repo-url> /opt/botopros
cd /opt/botopros
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # заполните реальными значениями

sudo cp deploy/botopros.service /etc/systemd/system/botopros.service
sudo systemctl daemon-reload
sudo systemctl enable --now botopros
sudo journalctl -u botopros -f   # смотреть логи
```

## Команды бота (только для администратора)

- `/newpoll` — создать опрос: название → варианты (`Текст | ДД.ММ.ГГГГ`) → `/done` → chat id или пересылка сообщения из чата
- `/editpoll` — изменить/удалить вариант существующего опроса
```

- [ ] **Step 3: Commit**

```bash
git add deploy/botopros.service README.md
git commit -m "docs: add systemd deployment unit and README"
```

- [ ] **Step 4: Manual end-to-end scenario walkthrough (in a real test chat, not production)**

Using the bot started in Task 17 Step 3, and a private test group chat with a few test accounts:

1. `/newpoll` in DM with the bot → add 2 date options → `/done` → send the test group's chat id.
   Expected: poll message with 2 buttons appears in the test group.
2. Vote from 4 different accounts on one option within a few seconds of each other.
   Expected: button label counts update after each vote; after the last vote, wait 15 minutes — the "проголосовало 4 человека" message appears tagging the admin.
3. Unvote from one account within the 15-minute window (before the message above fires).
   Expected: no "4 человека" message is ever sent for that cycle.
4. After the "4 человека" message has fired, unvote until the count drops below 4.
   Expected: "снова меньше 4х человек" message appears immediately.
5. `/editpoll` → pick the poll → pick an option with existing votes → `text` → send new text.
   Expected: poll message in the chat updates; a notification tagging the voters appears.
6. `/editpoll` → pick an option with existing votes → `delete`.
   Expected: option disappears from the poll message; voters are notified; any pending 15-minute timer for that option is cancelled (no stray message 15 minutes later).
7. Create an option dated tomorrow, get it to 4 confirmed votes, wait for 19:00 Europe/Moscow (or temporarily lower `REMINDER_TIME` in `.env` for the test and restart the bot).
   Expected: reminder message listing participants appears once, not repeated on subsequent days.

Record any deviations and fix before considering the bot production-ready.
