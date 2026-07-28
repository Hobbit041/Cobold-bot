# DATA_DIR-relative DB paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot's SQLite databases land in bothost.ru's persistent `/app/data` volume so polls and scheduled jobs survive restarts/redeploys.

**Architecture:** `bot/config.py` learns a `DATA_DIR` env var and resolves relative `DB_PATH`/`JOBS_DB_PATH` values *inside* it (absolute paths pass through unchanged). `bot/main.py` creates the parent directory of each DB file at startup. The Dockerfile stops setting misleading absolute `ENV DB_PATH`/`JOBS_DB_PATH` (the panel overrides them anyway) and keeps only `DATA_DIR=/app/data`.

**Tech Stack:** Python 3.12, SQLAlchemy async + aiosqlite, APScheduler, aiogram, pytest.

## Global Constraints

- Do NOT change the DB schema, models, or poll/voting/reminder logic — storage location only.
- Relative paths with an unset/empty `DATA_DIR` MUST stay unchanged (preserves local-dev and systemd-VPS behavior where cwd persists).
- No data migration: old databases are already lost; nothing to move.
- Follow existing style: `from __future__ import annotations`, stdlib `os.path`, no new dependencies.

---

### Task 1: Resolve DB paths relative to DATA_DIR in config

**Files:**
- Modify: `bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.db_path` and `Config.jobs_db_path` are now DATA_DIR-resolved absolute paths on bothost (relative unchanged when `DATA_DIR` unset). No signature change to `load_config()`.

- [ ] **Step 1: Write the failing tests**

Add these three tests to `tests/test_config.py`. They set the required base env vars and `delenv("DATA_DIR")` where they want the "unset" behavior, so they are deterministic regardless of the host environment.

```python
def test_relative_db_paths_resolve_under_data_dir(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("DATA_DIR", "/app/data")
    monkeypatch.setenv("DB_PATH", "poll_bot.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "jobs.sqlite3")

    config = load_config()

    import os
    assert config.db_path == os.path.join("/app/data", "poll_bot.sqlite3")
    assert config.jobs_db_path == os.path.join("/app/data", "jobs.sqlite3")


def test_absolute_db_paths_are_left_unchanged(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("DATA_DIR", "/app/data")
    monkeypatch.setenv("DB_PATH", "/somewhere/else/poll.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "/somewhere/else/jobs.sqlite3")

    config = load_config()

    assert config.db_path == "/somewhere/else/poll.sqlite3"
    assert config.jobs_db_path == "/somewhere/else/jobs.sqlite3"


def test_relative_db_paths_unchanged_without_data_dir(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("DB_PATH", "poll_bot.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "jobs.sqlite3")

    config = load_config()

    assert config.db_path == "poll_bot.sqlite3"
    assert config.jobs_db_path == "jobs.sqlite3"
```

Also harden the existing `test_load_config_reads_env` so a stray `DATA_DIR` in the host env can't break it: add `monkeypatch.delenv("DATA_DIR", raising=False)` near its other `setenv` calls (it asserts the relative paths stay unchanged).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: the three new tests FAIL — `test_relative_db_paths_resolve_under_data_dir` fails because `db_path` is still the bare relative string (`poll_bot.sqlite3`), not `/app/data/poll_bot.sqlite3`. The other two may already pass; that is fine.

- [ ] **Step 3: Implement the resolver in `bot/config.py`**

Add a module-level helper and apply it inside `load_config()`. Full edited region of `bot/config.py`:

```python
def _require_env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it in your hosting panel (or .env) before starting the bot."
        ) from None


def _resolve_data_path(path: str, data_dir: str) -> str:
    """Resolve a DB path against DATA_DIR.

    Absolute paths are returned unchanged. Relative paths are placed inside
    DATA_DIR when it is set, so bothost.ru's persistent /app/data volume is
    used even when the panel supplies bare relative filenames. With DATA_DIR
    unset, relative paths are left as-is (local dev / systemd, where the
    working directory already persists).
    """
    if os.path.isabs(path) or not data_dir:
        return path
    return os.path.join(data_dir, path)


def load_config() -> Config:
    bot_token = _require_env("BOT_TOKEN")
    admin_id = int(_require_env("ADMIN_ID"))
    admin_username = _require_env("ADMIN_USERNAME")
    timezone = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Europe/Moscow"))

    reminder_time = os.environ.get("REMINDER_TIME", "19:00")
    hour_str, minute_str = reminder_time.split(":")

    data_dir = os.environ.get("DATA_DIR", "")
    db_path = _resolve_data_path(os.environ.get("DB_PATH", "poll_bot.sqlite3"), data_dir)
    jobs_db_path = _resolve_data_path(os.environ.get("JOBS_DB_PATH", "jobs.sqlite3"), data_dir)
    threshold_debounce_seconds = int(os.environ.get("THRESHOLD_DEBOUNCE_SECONDS", "900"))

    return Config(
        bot_token=bot_token,
        admin_id=admin_id,
        admin_username=admin_username,
        timezone=timezone,
        reminder_hour=int(hour_str),
        reminder_minute=int(minute_str),
        db_path=db_path,
        jobs_db_path=jobs_db_path,
        threshold_debounce_seconds=threshold_debounce_seconds,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: all tests PASS (the three new ones plus the existing three).

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "fix: resolve DB paths under DATA_DIR so bothost /app/data is used"
```

---

### Task 2: Ensure DB parent directories exist at startup

**Files:**
- Modify: `bot/main.py:52-61` (the start of `main()`, around `create_engine_and_sessionmaker` / `create_scheduler`)

**Interfaces:**
- Consumes: `config.db_path`, `config.jobs_db_path` (from Task 1).
- Produces: nothing new; guarantees the parent directories exist before SQLite opens the files.

- [ ] **Step 1: Add directory creation before opening the databases**

In `bot/main.py`, immediately after `config = load_config()` (currently line 58) and before `engine, session_maker = create_engine_and_sessionmaker(config.db_path)`, insert:

```python
    # SQLite won't create missing parent directories. On bothost.ru the
    # persistent volume /app/data exists, but creating it here is a cheap
    # safety net and also covers first-run local setups.
    for _db_file in (config.db_path, config.jobs_db_path):
        _parent = os.path.dirname(_db_file)
        if _parent:
            os.makedirs(_parent, exist_ok=True)
```

`os` is already imported at the top of `bot/main.py`, so no new import is needed.

- [ ] **Step 2: Verify the full test suite still passes**

Run: `python -m pytest -q`
Expected: PASS (no regressions; this change has no unit test — it is startup wiring exercised by manual/deploy verification).

- [ ] **Step 3: Commit**

```bash
git add bot/main.py
git commit -m "fix: create DB parent directories at startup"
```

---

### Task 3: Clean up Dockerfile and document DATA_DIR

**Files:**
- Modify: `Dockerfile:11-16`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: the DATA_DIR behavior from Task 1.
- Produces: documentation and image env consistent with the new model.

- [ ] **Step 1: Simplify the Dockerfile env block**

In `Dockerfile`, replace the current block:

```dockerfile
# bothost.ru persists /app/data across redeploys; keep the sqlite databases there
# so poll history and scheduled reminders survive a rebuild.
ENV DATA_DIR=/app/data
ENV DB_PATH=/app/data/poll_bot.sqlite3
ENV JOBS_DB_PATH=/app/data/jobs.sqlite3
RUN mkdir -p /app/data
```

with:

```dockerfile
# bothost.ru persists /app/data across redeploys. The app resolves relative
# DB_PATH/JOBS_DB_PATH inside DATA_DIR, so setting DATA_DIR is enough to keep
# poll history and scheduled reminders in the persistent volume. (Absolute
# ENV DB_PATH here would be overridden by the panel's env vars anyway.)
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data
```

- [ ] **Step 2: Document DATA_DIR in `.env.example`**

Replace the `DB_PATH`/`JOBS_DB_PATH` lines in `.env.example` with a `DATA_DIR` line and a note. The file becomes:

```
BOT_TOKEN=123456:ABC-DEF...
ADMIN_ID=123456789
ADMIN_USERNAME=your_username
BOT_TIMEZONE=Europe/Moscow
REMINDER_TIME=19:00
# On bothost.ru set DATA_DIR=/app/data (the persistent volume). Relative
# DB_PATH/JOBS_DB_PATH below are resolved inside DATA_DIR; leave DATA_DIR
# empty for local dev to keep the sqlite files in the working directory.
DATA_DIR=
DB_PATH=poll_bot.sqlite3
JOBS_DB_PATH=jobs.sqlite3
THRESHOLD_DEBOUNCE_SECONDS=900
```

- [ ] **Step 3: Add a persistence note to `README.md`**

Under the local-run section (after the deploy block, near the existing `MemoryStorage` note around line 31), add:

```markdown
> **Хранилище на bothost.ru.** Данные (SQLite-базы опросов и заданий)
> переживают рестарт только в персистентном томе `/app/data`. Приложение
> разрешает относительные `DB_PATH`/`JOBS_DB_PATH` внутри `DATA_DIR`, поэтому
> в панели bothost достаточно задать `DATA_DIR=/app/data`. Локально `DATA_DIR`
> оставляют пустым — базы кладутся в рабочий каталог.
```

- [ ] **Step 4: Verify nothing is broken**

Run: `python -m pytest -q`
Expected: PASS (docs/Dockerfile changes don't affect tests; this confirms no accidental edits elsewhere).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .env.example README.md
git commit -m "docs: document DATA_DIR persistence and simplify Dockerfile env"
```

---

## Self-Review

**Spec coverage:**
- Resolver rules + matrix → Task 1 (helper `_resolve_data_path`, three tests covering all three matrix rows). ✓
- Directory guarantee at startup → Task 2. ✓
- Dockerfile cleanup (drop `ENV DB_PATH`/`JOBS_DB_PATH`, keep `DATA_DIR` + mkdir) → Task 3 Step 1. ✓
- `.env.example` / README docs → Task 3 Steps 2-3. ✓
- Tests for resolving → Task 1 Step 1 (all four spec test cases: relative+DATA_DIR, absolute+DATA_DIR, relative-no-DATA_DIR, both DB and jobs paths). ✓
- Out-of-scope items (no migration, no schema change) → honored via Global Constraints. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code and exact commands. ✓

**Type consistency:** Helper named `_resolve_data_path` consistently in Task 1. `Config` field names (`db_path`, `jobs_db_path`) match `bot/config.py` and are consumed by that exact name in Task 2. No new types introduced. ✓
