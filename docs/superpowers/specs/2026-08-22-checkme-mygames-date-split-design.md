# /checkme — фильтр по дате, и новая /mygames — дизайн

Дата: 2026-08-22

## Назначение

`/checkme` (см. `2026-08-22-checkme-design.md`) сейчас показывает
пользователю все его голоса с датой, независимо от того, прошла игра
или нет. Нужно разделить это на две команды:

- `/checkme` — только будущие и сегодняшние игры
  (`Option.date >= сегодня`), в прежнем хронологическом порядке
  (ближайшая первой).
- `/mygames` (новая) — только прошедшие игры (`Option.date < сегодня`),
  в хронологическом порядке от самой старой к более новой (по
  выбору пользователя — «история» читается сверху вниз как она
  происходила).

`/mygames` во всём остальном зеркалит `/checkme`: доступна любому
пользователю, отвечает прямо в чат вызова, использует те же
кликабельные HTML-ссылки, молча пропускает записи без даты / с
недоступным чатом / без рабочей ссылки — все решения из исходного
дизайна `/checkme` (включая orphaned-опросы наравне с активными и
`parse_mode="HTML"` на обоих ответах, включая пустой список) переносятся
без изменений.

## Как считается «сегодня»

Через таймзону бота — `dt.datetime.now(timezone).date()`, где
`timezone: ZoneInfo` берётся из `Config.timezone`
(`BOT_TIMEZONE`, по умолчанию `Europe/Moscow`). Это тот же приём,
что уже использует `jobs.send_due_reminders` (`bot/jobs.py:109`) для
вычисления «сегодня»/«завтра» при рассылке напоминаний — здесь он
переиспользуется, а не изобретается заново. `timezone` попадёт в
хендлеры так же, как `admin_mention`/`admin_id`/`session_maker` —
через kwarg в `dp.start_polling(...)`.

Дата вычисляется заново при каждом вызове команды (а не один раз при
старте бота) — иначе бот, работающий сутками напролёт, начал бы путать
сегодня со вчера.

## Реализация

### `bot/repo.py`

`get_votes_by_user` получает два новых опциональных параметра:

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

Оба параметра по умолчанию `None` (без фильтрации) — существующие
вызовы и тесты, не передающие эти аргументы, продолжают работать как
раньше. `ORDER BY Option.date` остаётся возрастающим для обеих команд
— единственная разница между `/checkme` и `/mygames` в том, какая
граница (`on_or_after` вместо `before`) применяется, а не в
направлении сортировки.

### `bot/formatting.py`

- `checkme_line` переименовывается в `record_line` (сигнатура и тело
  не меняются) — теперь используется обеими командами, а не только
  `/checkme`.
- `checkme_header`/`checkme_empty_text` остаются без изменений.
- Новые функции:
  ```python
  def mygames_header(mention: str) -> str:
      return f"{html.escape(mention)}, вы играли:"


  def mygames_empty_text(mention: str) -> str:
      return f"{html.escape(mention)}, у вас нет прошедших игр."
  ```

### `bot/handlers/checkme.py`

Оба хендлера остаются в этом файле (общая логика существенно больше,
чем то, что их отличает). Общие приватные хелперы:

```python
async def _build_lines(bot: Bot, rows: list[tuple[Poll, Option]]) -> list[str]:
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
```

`handle_checkme` (уже существует) переписывается на использование
этих хелперов и получает дату:

```python
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
```

Новый `handle_mygames`:

```python
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

Оба хендлера регистрируются на уже существующем `router = Router(name="checkme")`
— отдельный роутер/файл для `/mygames` не создаётся.

### `bot/main.py`

`dp.start_polling(...)` получает новый kwarg:

```python
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

Регистрация роутера (`dp.include_router(checkme.router)`) не меняется
— она уже подключает оба хендлера, живущих в одном файле.

## Тестирование

Даты в тестах вычисляются относительно реального времени
(`dt.datetime.now(tz).date() ± timedelta(...)`), как уже принято в
`tests/test_jobs.py` — никакого мока часов не требуется, и тесты не
протухнут по мере того, как реальная дата уходит вперёд.

- `tests/test_repo_voting.py`: новые тесты на `on_or_after` (голос
  сегодня и в будущем — попадает, вчерашний — нет) и `before` (голос
  вчера и раньше — попадает, сегодняшний и будущий — нет). Существующие
  тесты (без аргументов границ) не меняются.
- `tests/test_formatting.py`: переименовать `checkme_line` →
  `record_line` в тестах; добавить тесты на `mygames_header`/
  `mygames_empty_text` (по образцу уже существующих
  `checkme_header`/`checkme_empty_text`).
- `tests/test_handlers_checkme.py`: существующие тесты `/checkme`
  обновляются — их фикстуры используют даты в прошлом (`2026-08-01`,
  `2026-09-01` и т.п.), которые перестанут проходить фильтр
  `on_or_after=today` при запуске тестов в будущем; даты переводятся на
  относительные (`today + timedelta(...)`), и хендлеры теперь
  вызываются с `timezone=ZoneInfo("Europe/Moscow")`. Добавляются
  аналогичные тесты для `handle_mygames` (список, пропуск при ошибке
  `get_chat`, пропуск без рабочей ссылки, пустой список) с датами в
  прошлом.
