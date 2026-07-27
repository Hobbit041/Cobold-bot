# Dateless-Option Notifications & /revoll Reorder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop bothering people with booking/change notifications for poll options that have no date, show the date alongside the text in the "your voted option changed" notifications, and add a `/revoll` command to `/editpoll` for reordering a poll's options by number.

**Architecture:** Four small, mostly independent edits to the existing `bot/formatting.py`, `bot/jobs.py`, `bot/repo.py`, and `bot/handlers/admin_edit.py` modules — no new files, no schema changes (reordering reuses the existing `Option.position` column). Each task is TDD: update/add a test, watch it fail, implement, watch it pass, commit.

**Tech Stack:** Python, aiogram 3 (FSM `Router`/`StatesGroup`), SQLAlchemy async ORM, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-07-27-dateless-options-and-reorder-design.md`

---

### Task 1: `formatting.py` — dated labels in the "option changed" notifications

**Files:**
- Modify: `bot/formatting.py:46-59` (the two functions below)
- Test: `tests/test_formatting.py:73-91`

- [ ] **Step 1: Update the failing/changed tests in `tests/test_formatting.py`**

Replace lines 73–91 (the `test_option_deleted_notification_*` and
`test_option_text_changed_notification` tests) with:

```python
def test_option_deleted_notification_lists_voters():
    text = option_deleted_notification("24.07", dt.date(2026, 7, 24), ["@alice", "Bob"])
    assert text == (
        "@alice, Bob, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24 июля (24.07)» удалён."
    )


def test_option_deleted_notification_without_voters():
    text = option_deleted_notification("24.07", dt.date(2026, 7, 24), [])
    assert text == (
        "вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24 июля (24.07)» удалён."
    )


def test_option_deleted_notification_without_date():
    text = option_deleted_notification("Во что поиграть", None, ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «Во что поиграть» удалён."
    )


def test_option_text_changed_notification():
    text = option_text_changed_notification(
        "24.07", "24.07 (уточнено время)", dt.date(2026, 7, 24), ["@alice"]
    )
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24 июля (24.07)» → «24 июля (24.07 (уточнено время))»."
    )


def test_option_text_changed_notification_without_date():
    text = option_text_changed_notification("24.07", "24.07 (уточнено время)", None, ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24.07» → «24.07 (уточнено время)»."
    )
```

(`test_option_date_changed_notification*` tests below stay untouched — that
function's signature and behavior aren't changing.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_formatting.py -v -k "deleted_notification or text_changed_notification"`
Expected: FAIL — `TypeError: option_deleted_notification() takes 2 positional arguments but 3 were given` (and similarly for `option_text_changed_notification`).

- [ ] **Step 3: Implement in `bot/formatting.py`**

Replace the current `option_deleted_notification` / `option_text_changed_notification`
(lines 46–59) with:

```python
def _dated_label(option_text: str, option_date: dt.date | None) -> str:
    if option_date is None:
        return option_text
    return f"{format_date_ru(option_date)} ({option_text})"


def option_deleted_notification(
    option_text: str, option_date: dt.date | None, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    label = _dated_label(option_text, option_date)
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: вариант «{label}» удалён."
    )


def option_text_changed_notification(
    old_text: str, new_text: str, option_date: dt.date | None, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    old_label = _dated_label(old_text, option_date)
    new_label = _dated_label(new_text, option_date)
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{old_label}» → «{new_label}»."
    )
```

- [ ] **Step 4: Run the full formatting test file**

Run: `pytest tests/test_formatting.py -v`
Expected: PASS (all tests, including the untouched `option_date_changed_notification` ones).

- [ ] **Step 5: Commit**

```bash
git add bot/formatting.py tests/test_formatting.py
git commit -m "feat: include date in option-deleted/text-changed voter notifications"
```

---

### Task 2: `jobs.py` — no threshold-reached announcement for dateless options

**Files:**
- Modify: `bot/jobs.py:69-75` (inside `check_threshold`)
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Add the failing test**

Add to `tests/test_jobs.py` (near the other `test_threshold_check_callback_*` tests):

```python
async def test_threshold_check_callback_skips_option_without_date(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=555, title="Игра", options=[("Во что поиграть", None)]
        )
        option = (await repo.get_poll_options(session, poll.id))[0]
        for user_id in range(4):
            await repo.toggle_vote(
                session, option.id, user_id=user_id, username=f"user{user_id}", first_name=f"User{user_id}"
            )

    fake_bot = FakeBot()
    jobs.configure(fake_bot, session_maker, admin_mention="@admin", timezone=ZoneInfo("Europe/Moscow"))
    await jobs.check_threshold(option.id)

    assert fake_bot.sent_messages == []
    async with session_maker() as session:
        assert await repo.is_announced(session, option.id) is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_jobs.py -v -k skips_option_without_date`
Expected: FAIL — a message is sent and `is_announced` becomes `True` (current code has no date check).

- [ ] **Step 3: Implement in `bot/jobs.py`**

In `check_threshold`, right after the existing `is_deleted` check (around line 71),
add the early return:

```python
        async with session_maker() as session:
            option = await session.get(repo.Option, option_id)
            if option is None or option.is_deleted:
                return
            if option.date is None:
                return

            count = await repo.get_vote_count(session, option_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_jobs.py -v`
Expected: PASS (all tests, including the pre-existing threshold ones).

- [ ] **Step 5: Commit**

```bash
git add bot/jobs.py tests/test_jobs.py
git commit -m "feat: never announce threshold reached for options without a date"
```

---

### Task 3: `repo.py` — `reorder_options`

**Files:**
- Modify: `bot/repo.py` (add function near `edit_option_date`, ~line 150)
- Test: `tests/test_repo_edit.py`

- [ ] **Step 1: Add the failing test**

Add to `tests/test_repo_edit.py`:

```python
async def test_reorder_options_updates_position_order(session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=1,
            title="Игра",
            options=[("A", None), ("B", None), ("C", None), ("D", None)],
        )
        options = await repo.get_poll_options(session, poll.id)
        ids = [o.id for o in options]

    async with session_maker() as session:
        await repo.reorder_options(session, [ids[2], ids[0], ids[3], ids[1]])

    async with session_maker() as session:
        reordered = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in reordered] == ["C", "A", "D", "B"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_repo_edit.py -v -k reorder_options`
Expected: FAIL — `AttributeError: module 'bot.repo' has no attribute 'reorder_options'`.

- [ ] **Step 3: Implement in `bot/repo.py`**

Add right after `edit_option_date`:

```python
async def reorder_options(session: AsyncSession, ordered_option_ids: list[int]) -> None:
    for position, option_id in enumerate(ordered_option_ids):
        option = await session.get(Option, option_id)
        option.position = position
    await session.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_repo_edit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/repo.py tests/test_repo_edit.py
git commit -m "feat: add repo.reorder_options to persist a new option order"
```

---

### Task 4: `admin_edit.py` — suppress voter notifications when the option had no date

**Files:**
- Modify: `bot/handlers/admin_edit.py:204-247` (`apply_new_text`), `:250-301` (`apply_new_date`), `:304-340` (`_apply_delete`)
- Test: `tests/test_handlers_admin_edit.py`

This depends on Task 1 (new `formatting` signatures).

- [ ] **Step 1: Update existing tests to expect the dated label**

In `tests/test_handlers_admin_edit.py`:

`test_edit_text_notifies_existing_voters` — change the `send_message` assertion to:

```python
    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24 июля (24.07)» → «24 июля (24.07 (в 19:00))».",
        message_thread_id=None,
    )
```

`test_delete_option_notifies_and_removes_it` — change the `send_message` assertion to:

```python
    fake_bot.send_message.assert_awaited_once_with(
        chat_id=100,
        text="@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24 июля (24.07)» удалён.",
        message_thread_id=None,
    )
```

`test_apply_new_date_on_option_with_no_prior_date` — the option had **no** date
before this edit, so under the new rule no notification goes out. Replace the
`fake_bot.send_message.assert_awaited_once_with(...)` block with:

```python
    fake_bot.send_message.assert_not_awaited()

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].date == dt.date(2026, 7, 25)
```

- [ ] **Step 2: Add two new tests for the suppression behavior**

Add to `tests/test_handlers_admin_edit.py`:

```python
async def test_edit_text_on_option_without_date_sends_no_notification(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[])
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = await repo.add_option(session, poll.id, "Во что поиграть", None)
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
    await apply_new_text(
        FakeMessage("Во что-нибудь поиграть"), state, bot=fake_bot, session_maker=session_maker
    )

    fake_bot.edit_message_text.assert_awaited_once()
    fake_bot.send_message.assert_not_awaited()

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert options[0].text == "Во что-нибудь поиграть"


async def test_delete_option_without_date_sends_no_notification(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=100, title="Игра", options=[])
        await repo.set_poll_message(session, poll.id, message_id=42)
        option = await repo.add_option(session, poll.id, "Во что поиграть", None)
        await repo.toggle_vote(session, option.id, user_id=5, username="alice", first_name="Alice")

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await select_option(FakeMessage("1"), state)
    await select_action(
        FakeMessage("delete"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )

    fake_bot.send_message.assert_not_awaited()

    async with session_maker() as session:
        remaining = await repo.get_poll_options(session, poll.id)
        assert remaining == []
```

- [ ] **Step 3: Run the affected tests to verify they fail**

Run: `pytest tests/test_handlers_admin_edit.py -v`
Expected: FAIL on the three updated tests (old code sends the old-format text /
sends a notification when it shouldn't) and the two new tests (notification is
sent when it shouldn't be, or the call errors on the old `option_deleted_notification`/
`option_text_changed_notification` signature).

- [ ] **Step 4: Implement in `bot/handlers/admin_edit.py`**

In `apply_new_text` (around line 221), capture the date and gate on it:

```python
        old_text = option.text
        option_date = option.date
        voters = await repo.get_voters(session, option_id)
        updated = await repo.edit_option_text(session, option_id, new_text)
```

and change the notification block (around line 235):

```python
    notification_text = None
    if voters and option_date is not None:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_text_changed_notification(old_text, new_text, option_date, mentions)
```

In `apply_new_date` (around line 286), change the existing gate from `if voters:`
to:

```python
    notification_text = None
    if voters and old_date is not None:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_date_changed_notification(updated.text, old_date, new_date, mentions)
```

(`option_date_changed_notification`'s own signature/body is unchanged — only the
gating condition changes.)

In `_apply_delete` (around line 312), capture the date and gate on it:

```python
        option_text = option.text
        option_date = option.date
        voters = await repo.get_voters(session, option_id)
        poll = await repo.get_poll(session, option.poll_id)
        await repo.delete_option(session, option_id)
```

and change the notification block (around line 328):

```python
    notification_text = None
    if voters and option_date is not None:
        mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
        notification_text = formatting.option_deleted_notification(option_text, option_date, mentions)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: don't notify voters when an option without a date changes"
```

---

### Task 5: `admin_edit.py` — `/revoll` reorder command

**Files:**
- Modify: `bot/handlers/admin_edit.py` (add `waiting_new_order` state + two handlers)
- Test: `tests/test_handlers_admin_edit.py`

This depends on Task 3 (`repo.reorder_options`).

- [ ] **Step 1: Add the failing tests**

Add to `tests/test_handlers_admin_edit.py` (import `start_reorder, apply_new_order`
alongside the other names already imported from `bot.handlers.admin_edit` at the
top of the file):

```python
async def test_revoll_reorders_options_and_refreshes_message(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=100,
            title="Игра",
            options=[("A", None), ("B", None), ("C", None), ("D", None)],
        )
        await repo.set_poll_message(session, poll.id, message_id=42)

    state = _state()
    fake_bot = AsyncMock()
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await start_reorder(FakeMessage("/revoll"), state, session_maker=session_maker, scheduler=scheduler)
    assert await state.get_state() == EditPollStates.waiting_new_order.state

    await apply_new_order(
        FakeMessage("1 3 4 2"), state, bot=fake_bot, session_maker=session_maker, scheduler=scheduler
    )

    fake_bot.edit_message_text.assert_awaited_once()
    fake_bot.send_message.assert_not_awaited()
    assert await state.get_state() is None

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in options] == ["A", "C", "D", "B"]


async def test_revoll_rejects_invalid_order_and_stays_in_state(tmp_path, session_maker):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=100, title="Игра", options=[("A", None), ("B", None)]
        )
        await repo.set_poll_message(session, poll.id, message_id=42)

    state = _state()
    fake_bot = AsyncMock()

    await start_edit_poll(FakeMessage("/editpoll"), state, admin_id=1, session_maker=session_maker)
    await select_poll(FakeMessage("1"), state, session_maker=session_maker)
    await start_reorder(FakeMessage("/revoll"), state, session_maker=session_maker)

    bad_message = FakeMessage("1 1")
    await apply_new_order(bad_message, state, bot=fake_bot, session_maker=session_maker)

    assert await state.get_state() == EditPollStates.waiting_new_order.state
    fake_bot.edit_message_text.assert_not_awaited()
    bad_message.answer.assert_awaited_once()

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll.id)
        assert [o.text for o in options] == ["A", "B"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_handlers_admin_edit.py -v -k revoll`
Expected: FAIL — `ImportError` (`start_reorder`/`apply_new_order` don't exist yet).

- [ ] **Step 3: Implement in `bot/handlers/admin_edit.py`**

Add the new state to `EditPollStates` (around line 36-43):

```python
class EditPollStates(StatesGroup):
    waiting_poll_selection = State()
    waiting_option_selection = State()
    waiting_action = State()
    waiting_new_text = State()
    waiting_new_date = State()
    waiting_new_option = State()
    waiting_new_order = State()
```

Add the two new handlers right after `receive_new_option` and before
`select_option` (registration order matters: this `Command("revoll")` handler
must be registered before the plain, filter-less `select_option` handler on the
same state, exactly like `start_add_option` already is):

```python
@router.message(EditPollStates.waiting_option_selection, Command("revoll"))
async def start_reorder(message: Message, state: FSMContext, session_maker, scheduler=None) -> None:
    data = await state.get_data()
    poll_id = data["poll_id"]

    async with session_maker() as session:
        options = await repo.get_poll_options(session, poll_id)

    lines = [
        f"{i + 1}. {opt.text}" + (f" ({date_utils.format_date_ru(opt.date)})" if opt.date else "")
        for i, opt in enumerate(options)
    ]
    await state.update_data(option_ids=[opt.id for opt in options])
    await state.set_state(EditPollStates.waiting_new_order)
    await cleanup_and_answer(
        message,
        state,
        "Текущий порядок:\n" + "\n".join(lines)
        + "\n\nВведите новый порядок номеров через пробел, например: 1 3 4 2",
        scheduler=scheduler,
    )


@router.message(EditPollStates.waiting_new_order)
async def apply_new_order(message: Message, state: FSMContext, bot: Bot, session_maker, scheduler=None) -> None:
    data = await state.get_data()
    option_ids = data["option_ids"]
    poll_id = data["poll_id"]
    n = len(option_ids)

    parts = (message.text or "").split()
    valid = False
    indices: list[int] = []
    if len(parts) == n and all(p.isdigit() for p in parts):
        indices = [int(p) - 1 for p in parts]
        valid = sorted(indices) == list(range(n))

    if not valid:
        await cleanup_and_answer(
            message,
            state,
            f"Некорректный порядок. Нужно указать все номера от 1 до {n} через пробел, "
            "каждый ровно один раз. Например: 1 3 4 2",
            scheduler=scheduler,
        )
        return

    ordered_option_ids = [option_ids[i] for i in indices]

    async with session_maker() as session:
        await repo.reorder_options(session, ordered_option_ids)
        poll = await repo.get_poll(session, poll_id)
        poll_options = await repo.get_poll_options(session, poll_id)
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    success = await _refresh_and_notify(
        bot, poll, poll_options, counts, voters_by_option, [], None, session_maker
    )

    await state.clear()
    await cleanup_and_answer(
        message,
        state,
        "Порядок вариантов обновлён." if success else _PARTIAL_FAILURE_MESSAGE,
        scheduler=scheduler,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_handlers_admin_edit.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: PASS (everything — this is the last task in the plan).

- [ ] **Step 6: Commit**

```bash
git add bot/handlers/admin_edit.py tests/test_handlers_admin_edit.py
git commit -m "feat: add /revoll command to reorder a poll's options"
```
