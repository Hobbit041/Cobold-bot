# Варианты без даты, подписи с датой и /revoll — дизайн

Дата: 2026-07-27

## Назначение

Четыре независимых изменения по итогам практического использования бота:

1. Варианты без даты (например, открытый "во что поиграть") не привязаны
   к конкретному дню и не подразумевают бронь — оповещение о достаточности
   голосов для неё для таких вариантов не нужно.
2. Уведомление голосовавшим "вариант изменился" сейчас показывает только
   текст варианта, без даты — нужно показывать оба, в формате
   `дата (текст)`.
3. Та же логика "вариант без даты не важен для брони" — если меняется
   (текст/дата/удаление) вариант, у которого на момент изменения не было
   даты, участников оповещать не нужно.
4. Команда `/revoll` внутри `/editpoll` для смены порядка вариантов по
   номерам.

## 1. Порог голосов не оповещает по вариантам без даты

Единственное место, где реально отправляется текст
`threshold_reached_text` ("...достаточно голосов для брони") —
`jobs.check_threshold`. Добавляется ранний выход сразу после проверки
`is_deleted`:

```python
async def check_threshold(option_id: int) -> None:
    ...
    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None or option.is_deleted:
            return
        if option.date is None:
            return
        ...
```

`threshold_logic.py` и `voting.py` не меняются: debounce-таймер
по-прежнему планируется/отменяется как раньше при пересечении порога —
он просто ничего не отправляет и не помечает `announced=True` по
срабатыванию для варианта без даты. Поскольку `announced` для такого
варианта навсегда остаётся `False`, ветка `ANNOUNCE_DROP` в
`threshold_logic.decide_action_after_vote_change` для него никогда не
сработает — значит и "оповещение об уменьшении голосов"
(`threshold_dropped_text`) для вариантов без даты никогда не пошлётся,
без отдельного условия под это.

## 2 и 3. Уведомление "вы проголосовали за вариант, но он изменился"

### Формат подписи

Новый приватный хелпер в `bot/formatting.py`:

```python
def _dated_label(option_text: str, option_date: dt.date | None) -> str:
    if option_date is None:
        return option_text
    return f"{format_date_ru(option_date)} ({option_text})"
```

Меняются сигнатуры (добавляется `option_date`):

```python
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

Дата одна и та же для старой и новой подписи в `option_text_changed_notification`,
так как правка текста саму дату не трогает. `option_date_changed_notification`
не меняется — там текст и обе даты уже показаны явным текстом ("«Игра»
перенесён с ... на ...").

### Подавление для вариантов без даты (было/стало)

В `bot/handlers/admin_edit.py`, в трёх местах, условие построения
`notification_text` расширяется: уведомление шлётся только если у
варианта **была** дата **до** изменения.

- `apply_new_text`: вместо `if voters:` — `if voters and option.date is not None:`,
  вызов с новым аргументом: `option_text_changed_notification(old_text, new_text, option.date, mentions)`.
- `apply_new_date`: вместо `if voters:` — `if voters and old_date is not None:`
  (`old_date` уже вычисляется в функции до правки).
- `_apply_delete`: добавляется `option_date = option.date` рядом с уже
  существующим `option_text = option.text` (до `repo.delete_option`);
  вместо `if voters:` — `if voters and option_date is not None:`, вызов —
  `option_deleted_notification(option_text, option_date, mentions)`.

Само изменение в БД и обновление сообщения опроса (`_refresh_poll_message`)
происходят всегда, независимо от даты — не отправляется только
уведомление участникам.

Побочный эффект: тест `test_apply_new_date_on_option_with_no_prior_date`
(вариант без даты получает дату) меняет ожидание с "уведомление
отправлено" на "уведомление не отправлено" — ровно тот случай, который
и обсуждался.

## 4. `/revoll` — изменение порядка вариантов

Команда работает внутри уже существующего `/editpoll`, в состоянии
`EditPollStates.waiting_option_selection` — там же, где сейчас можно
отправить `/addoption`.

Новое состояние:

```python
waiting_new_order = State()
```

### Запуск

```python
@router.message(EditPollStates.waiting_option_selection, Command("revoll"))
async def start_reorder(message, state, session_maker, scheduler=None) -> None:
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
```

Список перечитывается из БД заново (а не берётся из уже сохранённого в
FSM `option_ids`), чтобы показать актуальный порядок и держать
`option_ids` синхронным с тем, что реально видит админ прямо сейчас.

### Приём нового порядка

```python
@router.message(EditPollStates.waiting_new_order)
async def apply_new_order(message, state, bot, session_maker, scheduler=None) -> None:
    data = await state.get_data()
    option_ids = data["option_ids"]
    n = len(option_ids)

    parts = (message.text or "").split()
    valid = False
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
        poll = await repo.get_poll(session, data["poll_id"])
        poll_options = await repo.get_poll_options(session, data["poll_id"])
        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        voters_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }

    try:
        await _refresh_poll_message(bot, poll, poll_options, counts, voters_by_option, session_maker)
        success = True
    except Exception:
        logger.exception("Failed to refresh poll message for poll %s", poll.id)
        success = False

    await state.clear()
    await cleanup_and_answer(
        message, state, "Порядок вариантов обновлён." if success else _PARTIAL_FAILURE_MESSAGE,
        scheduler=scheduler,
    )
```

Невалидный ввод (неверная длина, не число, повтор, пропуск номера)
оставляет диалог в `waiting_new_order` и отвечает тем же сообщением об
ошибке — по аналогии с обработкой невалидного `/addoption`.

Участники **не уведомляются** — меняется только порядок отображения, ни
текст, ни дата, ни состав вариантов не затронуты (как и при `/addoption`,
который тоже не шлёт уведомление).

### `repo.reorder_options`

```python
async def reorder_options(session: AsyncSession, ordered_option_ids: list[int]) -> None:
    for position, option_id in enumerate(ordered_option_ids):
        option = await session.get(Option, option_id)
        option.position = position
    await session.commit()
```

## Реализация — что меняется в существующих файлах

- `bot/formatting.py`: новый приватный `_dated_label`; сигнатуры
  `option_deleted_notification` и `option_text_changed_notification`
  получают параметр `option_date`.
- `bot/jobs.py`: ранний выход в `check_threshold` для `option.date is None`.
- `bot/repo.py`: новая `reorder_options`.
- `bot/handlers/admin_edit.py`:
  - `apply_new_text`, `apply_new_date`, `_apply_delete` — условие
    отправки уведомления учитывает дату варианта до изменения;
    обновлённые вызовы форматтеров.
  - Новое состояние `EditPollStates.waiting_new_order`.
  - Новые хендлеры `start_reorder` (`Command("revoll")` в
    `waiting_option_selection`) и `apply_new_order`
    (`waiting_new_order`).

## Тестирование

- `tests/test_formatting.py`: обновить существующие тесты
  `option_deleted_notification`/`option_text_changed_notification` под
  новую сигнатуру и формат `дата (текст)`; добавить тесты на случай
  `option_date=None` (подпись остаётся просто текстом).
- `tests/test_jobs.py`: новый тест — `check_threshold` для варианта без
  даты с количеством голосов выше порога не вызывает `bot.send_message`
  и не помечает `announced=True`.
- `tests/test_handlers_admin_edit.py`:
  - обновить существующие тесты правки текста/удаления — ожидаемый текст
    уведомления теперь содержит дату;
  - обновить `test_apply_new_date_on_option_with_no_prior_date` —
    уведомление больше не отправляется;
  - новые тесты: правка текста/даты и удаление варианта **без** даты (с
    проголосовавшими) не отправляют уведомление, при этом сама правка/
    удаление в БД и обновление сообщения опроса происходят как обычно;
  - новые тесты на `/revoll`: успешная перестановка (проверить итоговый
    порядок `position`/порядок в отрисованном сообщении и клавиатуре),
    невалидный ввод (не то количество номеров, повтор, не число) — диалог
    остаётся в `waiting_new_order`, БД не тронута.
- `tests/test_repo_edit.py`: новый тест на `reorder_options` (создать
  опрос с несколькими вариантами, переставить, проверить порядок,
  возвращаемый `get_poll_options`).
