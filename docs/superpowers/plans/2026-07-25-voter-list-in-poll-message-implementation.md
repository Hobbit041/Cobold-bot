# Voter List In Poll Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the list of who voted for each option directly under that option's line in the poll message, always visible, updated on every vote/edit — no new button, no schema change.

**Architecture:** Extend `bot/formatting.format_option_line` with an optional `voter_mentions` parameter that appends an indented second line when non-empty. Update the three places that build the poll message text (`bot/handlers/voting.py`, `bot/handlers/admin_edit.py`'s `_refresh_poll_message`) to fetch each option's voters (via the existing `repo.get_voters`) inside the already-open DB session and pass mentions through. `bot/handlers/admin_create.py` needs no change — every option on a brand-new poll has zero voters, and the parameter defaults to producing the old single-line output.

**Tech Stack:** Same as the existing bot (Python 3.14, aiogram 3.30, SQLAlchemy async, pytest/pytest-asyncio) — no new dependencies.

---

## File Structure

- Modify: `bot/formatting.py` — `format_option_line` gains `voter_mentions: list[str] | None = None`
- Modify: `bot/handlers/voting.py` — fetch per-option voter mentions inside the existing session block, pass to `format_option_line`
- Modify: `bot/handlers/admin_edit.py` — `_refresh_poll_message` and `_refresh_and_notify` gain a `voters_by_option: dict[int, list[str]]` parameter; the three apply functions (`apply_new_text`, `apply_new_date`, `_apply_delete`) compute it inside their session blocks
- Modify: `tests/test_formatting.py`, `tests/test_handlers_voting.py`, `tests/test_handlers_admin_edit.py` — new/updated tests

No changes to `bot/handlers/admin_create.py`, `bot/models.py`, `bot/repo.py`, `bot/keyboards.py`, or `bot/db.py`.

---

### Task 1: Extend `format_option_line` with an optional voter list

**Files:**
- Modify: `bot/formatting.py`
- Modify: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_formatting.py` (alongside the existing imports/tests — add `format_option_line` to the existing `from bot.formatting import (...)` import block):

```python
def test_format_option_line_without_voters():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 2)
    assert line == "1. 24.07 (24 июля) — 2 🗳"


def test_format_option_line_with_voters():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 2, ["@alice", "Bob"])
    assert line == "1. 24.07 (24 июля) — 2 🗳\n   @alice, Bob"


def test_format_option_line_with_empty_voter_list():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 0, [])
    assert line == "1. 24.07 (24 июля) — 0 🗳"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_formatting.py -v`
Expected: FAIL — `format_option_line` doesn't accept a 5th positional argument (`TypeError`), and it isn't imported by name into the test file yet if not already present (check the existing import block first; add it if missing).

- [ ] **Step 3: Update the implementation**

In `bot/formatting.py`, replace:

```python
def format_option_line(index: int, option_text: str, option_date: dt.date, vote_count: int) -> str:
    return f"{index}. {option_text} ({format_date_ru(option_date)}) — {vote_count} 🗳"
```

with:

```python
def format_option_line(
    index: int,
    option_text: str,
    option_date: dt.date,
    vote_count: int,
    voter_mentions: list[str] | None = None,
) -> str:
    line = f"{index}. {option_text} ({format_date_ru(option_date)}) — {vote_count} 🗳"
    if voter_mentions:
        line += f"\n   {', '.join(voter_mentions)}"
    return line
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_formatting.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add bot/formatting.py tests/test_formatting.py
git commit -m "feat: let format_option_line append a voter list under each option"
```

---

### Task 2: Show voter names after voting

**Files:**
- Modify: `bot/handlers/voting.py`
- Modify: `tests/test_handlers_voting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_handlers_voting.py` (reuses the existing `FakeUser`/`FakeCallback`/`_noop_threshold_callback` helpers already in the file):

```python
async def test_handle_vote_toggle_message_shows_voter_names(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        voted_option, other_option = options

    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    fake_bot = AsyncMock()
    callback = FakeCallback(
        data=f"vote:{voted_option.id}", user=FakeUser(id=10, username="alice", first_name="Alice")
    )

    await handle_vote_toggle(
        callback,
        session_maker=session_maker,
        scheduler=scheduler,
        bot=fake_bot,
        admin_mention="@admin",
        threshold_check_callback=_noop_threshold_callback,
    )

    sent_text = fake_bot.edit_message_text.await_args.kwargs["text"]
    assert sent_text == (
        "📅 Игра\n\n"
        "1. 24.07 (24 июля) — 1 🗳\n"
        "   @alice\n"
        "2. 25.07 (25 июля) — 0 🗳"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py::test_handle_vote_toggle_message_shows_voter_names -v`
Expected: FAIL — the current message text has no voter line, so the first assertion fails.

- [ ] **Step 3: Update the implementation**

In `bot/handlers/voting.py`, inside the `async with session_maker() as session:` block, replace:

```python
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        option_text = option.text
```

with:

```python
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voter_mentions_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }
        option_text = option.text
```

Then, further down (still in `handle_vote_toggle`, after the `async with` block closes), replace:

```python
    lines = [
        formatting.format_option_line(i + 1, opt.text, opt.date, counts[opt.id])
        for i, opt in enumerate(poll_options)
    ]
```

with:

```python
    lines = [
        formatting.format_option_line(
            i + 1, opt.text, opt.date, counts[opt.id], voter_mentions_by_option[opt.id]
        )
        for i, opt in enumerate(poll_options)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_voting.py -v`
Expected: PASS (all tests in the file — the new one plus the 5 pre-existing ones, which don't assert on exact message body content so they're unaffected)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/voting.py tests/test_handlers_voting.py
git commit -m "feat: show voter names under each option after a vote"
```

---

### Task 3: Show voter names after admin edits (text/date/delete)

**Files:**
- Modify: `bot/handlers/admin_edit.py`
- Modify: `tests/test_handlers_admin_edit.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_handlers_admin_edit.py`:

```python
async def test_apply_new_text_shows_voter_names_for_all_options(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("24.07", dt.date(2026, 7, 24)), ("25.07", dt.date(2026, 7, 25))],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)
        options = await repo.get_poll_options(session, poll.id)
        edited_option, other_option = options
        await repo.toggle_vote(session, edited_option.id, user_id=5, username="alice", first_name="Alice")
        await repo.toggle_vote(session, other_option.id, user_id=6, username="bob", first_name="Bob")

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

    sent_text = fake_bot.edit_message_text.await_args.kwargs["text"]
    assert "1. 24.07 (в 19:00) (24 июля) — 1 🗳\n   @alice" in sent_text
    assert "2. 25.07 (25 июля) — 1 🗳\n   @bob" in sent_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py::test_apply_new_text_shows_voter_names_for_all_options -v`
Expected: FAIL — the refreshed message currently has no voter lines.

- [ ] **Step 3: Update the implementation**

In `bot/handlers/admin_edit.py`:

1. Update `_refresh_poll_message`'s signature and body:

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
    keyboard = keyboards.build_poll_keyboard([(opt.id, opt.text, counts[opt.id]) for opt in poll_options])
    await bot.edit_message_text(chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard)
```

2. Update `_refresh_and_notify`'s signature to accept and forward `voters_by_option`:

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

    if voters and notification_text is not None:
        try:
            await bot.send_message(chat_id=poll.chat_id, text=notification_text)
        except Exception:
            logger.exception("Failed to notify voters for poll %s", poll.id)
            ok = False

    return ok
```

3. In `apply_new_text`, inside the `async with session_maker() as session:` block, replace:

```python
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
```

with:

```python
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }
```

Then update its `_refresh_and_notify` call:

```python
    success = await _refresh_and_notify(bot, poll, poll_options, counts, voters_by_option, voters, notification_text)
```

4. Apply the identical two edits (add the `voters_by_option` comprehension right after the `counts` comprehension, and add `voters_by_option` as the 5th positional argument to `_refresh_and_notify`) in `apply_new_date` and in `_apply_delete`. In `_apply_delete`, `poll_options` at that point is already the post-delete list (fetched after `repo.delete_option(...)` runs), so the comprehension naturally excludes the deleted option — no extra care needed there.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && python -m pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (all tests in the file — the new one plus the 5 pre-existing ones, which don't assert on exact message body content so they're unaffected)

- [ ] **Step 5: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: show voter names under each option after admin edits"
```

---

### Task 4: Full-suite regression check and running-bot restart note

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `source .venv/Scripts/activate && python -m pytest -v`
Expected: PASS (all pre-existing tests plus the 4 new ones from Tasks 1-3 — no regressions, since `voter_mentions`/`voters_by_option` are purely additive and every existing assertion either doesn't touch message body text or only checks a substring that remains present)

- [ ] **Step 2: Confirm `bot.main` still imports cleanly**

Run: `source .venv/Scripts/activate && python -c "import bot.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Report to the user that the running bot process needs a restart**

This plan changes application code (`bot/formatting.py`, `bot/handlers/voting.py`, `bot/handlers/admin_edit.py`). If a bot instance is already running (started via `python -m bot.main`), it is running the old in-memory code and won't pick up these changes until restarted. No database schema changed, so a restart is the only step needed — existing polls/votes/data are untouched. Tell the user to restart the running bot process to pick up the change, and offer to do it for them.
