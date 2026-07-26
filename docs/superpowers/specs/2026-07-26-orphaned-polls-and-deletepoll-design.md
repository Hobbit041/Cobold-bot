# Осиротевшие опросы и /deletepoll — дизайн

Дата: 2026-07-26

## Назначение

Админ иногда подчищает старые/битые опросы, удаляя сообщение бота прямо в
Telegram. Запись об опросе при этом остаётся в БД навсегда (`status`
никогда не меняется с `"active"`), продолжая маячить в списках
`/editpoll`/`/copypoll`. Нажатие на кнопку голосования под таким (уже
несуществующим) сообщением тоже ничего не даёт голосующему — он просто не
видит сообщения, чтобы нажать.

Технический факт, определивший дизайн: у Telegram Bot API нет события
"сообщение удалено" — бот не может подписаться на уведомление об этом.
Единственный способ узнать — попытаться что-то сделать с конкретным
message_id (отредактировать/удалить) и поймать ошибку. Поскольку кнопки
голосования исчезают вместе с сообщением, `voting.py` физически не может
столкнуться с уже удалённым сообщением через клик (кнопки нет — некому
жать). Реально наткнуться на это может `admin_edit.py`, когда админ уже
выбрал именно этот опрос из списка `/editpoll` и пытается его
отредактировать. Поэтому периодическая фоновая проверка не нужна и не
запрашивалась — вместо неё: (1) реактивная пометка при естественном
столкновении с ошибкой, и (2) отдельная явная команда `/deletepoll` как
основной инструмент, которым админ должен пользоваться вместо ручного
удаления сообщения.

## Новый статус опроса — `"orphaned"`

`Poll.status` — уже существующее строковое поле (`bot/models.py`),
сейчас всегда `"active"`. Добавляется второе допустимое значение:
`"orphaned"` — опрос, чьё сообщение в Telegram подтверждённо пропало.
`/editpoll` (`admin_edit.py::start_edit_poll`) и `/copypoll`
(`admin_copy.py::start_copy_poll`) уже фильтруют
`select(Poll).where(Poll.status == "active")` — осиротевшие опросы
автоматически перестают в них попадать, без изменений в их коде.
Никакой миграции не требуется — это обычное строковое поле без
enum-ограничения на уровне БД.

## Реактивная пометка осиротевших опросов

В двух местах, где код вызывает `bot.edit_message_text(chat_id=poll.chat_id,
message_id=poll.message_id, ...)` и ловит исключение — `voting.py`
(`handle_vote_toggle`, после голоса) и `admin_edit.py`
(`_refresh_poll_message`, после правки текста/даты/удаления варианта) —
уточняем обработку: ловим конкретно `aiogram.exceptions.TelegramBadRequest`
и проверяем `"not found" in exc.message.lower()` (Telegram возвращает
именно такой текст для "message to edit not found"). Если совпало —
вызываем новую `repo.mark_poll_orphaned(session, poll.id)` (открывая
отдельную сессию через уже доступный в обоих местах `session_maker`).

Видимое поведение для пользователя/админа в обоих местах **не меняется**:
то же сообщение об ошибке, что и сейчас (лог + для `admin_edit.py` —
`_PARTIAL_FAILURE_MESSAGE`, для `voting.py` — тихий лог). Единственный
эффект — опрос с этого момента перестаёт попадать в списки
`/editpoll`/`/copypoll`. Любые другие исключения (сеть, "message is not
modified" и т.п.) по-прежнему просто логируются, статус не трогаем.

## `/deletepoll`

Новый файл `bot/handlers/admin_delete.py`, по структуре — как
`admin_copy.py`/`admin_edit.py` (список опросов по номеру, FSM в одно
состояние). Отличия от `/copypoll`:

- Работает из **любого** чата, включая личку — как `/editpoll` (команде
  не нужно знать, куда публиковать, только откуда удалять — а это уже
  хранится в `poll.chat_id`/`poll.message_id`).
- Список включает **все** опросы независимо от статуса (`active` и
  `orphaned`), без фильтра — иначе уже осиротевшие записи вообще нельзя
  будет вычистить из БД никаким способом. Рядом с уже осиротевшими
  опросами в списке добавляется пометка `[опрос удалён, есть только в
  БД]`, чтобы админ понимал, что удалять там нечего кроме записи в БД.
- Без подтверждения перед удалением (как и `select_action`/`delete` в
  `/editpoll` сейчас).
- При выборе номера: пробует `bot.delete_message(chat_id=poll.chat_id,
  message_id=poll.message_id)` (пропускается, если `message_id is None`
  — теоретически невозможно для реально опубликованного опроса, но
  дешёвая защита). Если `delete_message` падает (сообщение уже удалено
  вручную, или не хватает прав) — логируем и продолжаем, не блокируем
  очистку БД. Затем безусловно вызывает новую `repo.delete_poll`,
  отвечает "Опрос удалён."

## `repo.delete_poll`

По аналогии с уже существующей `repo.delete_option` (которая вручную,
без опоры на ORM cascade, чистит `Vote`/`ThresholdState`/`Reminder`)
— но полное, а не мягкое (`is_deleted`) удаление, и на уровне всего
опроса:

```python
async def delete_poll(session: AsyncSession, poll_id: int) -> None:
    result = await session.execute(select(Option).where(Option.poll_id == poll_id))
    options = list(result.scalars().all())

    for option in options:
        for vote in await get_voters(session, option.id):
            await session.delete(vote)
        threshold_state = await session.get(ThresholdState, option.id)
        if threshold_state:
            await session.delete(threshold_state)
        reminder = await session.get(Reminder, option.id)
        if reminder:
            await session.delete(reminder)
        await session.delete(option)

    poll = await session.get(Poll, poll_id)
    await session.delete(poll)
    await session.commit()
```

Запрос вариантов идёт напрямую (`select(Option).where(Option.poll_id ==
poll_id)`), а не через `repo.get_poll_options` — та фильтрует
`is_deleted`, а тут нужно удалить вообще все строки, включая уже
мягко-удалённые ранее через `/editpoll`.

## `repo.mark_poll_orphaned`

```python
async def mark_poll_orphaned(session: AsyncSession, poll_id: int) -> None:
    poll = await session.get(Poll, poll_id)
    if poll is not None:
        poll.status = "orphaned"
        await session.commit()
```

## Реализация — что меняется в существующих файлах

- `bot/repo.py`: добавляются `delete_poll`, `mark_poll_orphaned`.
- `bot/handlers/voting.py`: `except Exception:` вокруг
  `bot.edit_message_text` в `handle_vote_toggle` разбивается на
  `except TelegramBadRequest as exc:` (с проверкой `"not found"` и
  вызовом `mark_poll_orphaned` через новую `async with session_maker()`)
  и общий `except Exception:` для остального — оба продолжают логировать
  как сейчас.
- `bot/handlers/admin_edit.py`: `_refresh_poll_message` и
  `_refresh_and_notify` получают новый параметр `session_maker`
  (пробрасывается из трёх мест вызова — `apply_new_text`,
  `apply_new_date`, `_apply_delete`, у которых он уже есть как аргумент
  хендлера). Внутри `_refresh_poll_message` — та же логика: ловим
  `TelegramBadRequest`, при `"not found"` помечаем осиротевшим, затем
  **пере-рейзим** исключение дальше (чтобы `_refresh_and_notify`'s
  внешний `except Exception:` отработал как и сейчас — `ok = False`,
  `_PARTIAL_FAILURE_MESSAGE`; поведение ответа админу не меняется).
- Новый `bot/handlers/admin_delete.py` (см. выше).
- `bot/main.py`: регистрация `admin_delete.router` (после
  `dialog_control.router` — по той же причине, что и `admin_copy`:
  у `select_poll_to_delete` нет `Command(...)`-фильтра).

## Тестирование

- `tests/test_repo_poll.py`: юнит-тесты на `delete_poll` (создать опрос
  с вариантами, голосами, мягко удалённым вариантом — проверить, что
  после `delete_poll` не осталось ни одной связанной строки: `Poll`,
  `Option` (включая уже `is_deleted`), `Vote`, `ThresholdState`,
  `Reminder`) и на `mark_poll_orphaned` (статус меняется на
  `"orphaned"`).
- Новый `tests/test_handlers_admin_delete.py`, по образцу
  `test_handlers_admin_copy.py`: не-админ, пустой список опросов,
  листинг (включая пометку у `orphaned`-опроса), некорректный номер
  (включая `"0"`), полное удаление (проверить `bot.delete_message`
  вызван с правильными `chat_id`/`message_id`, и что `Poll`/`Option`
  реально пропали из БД), и отдельный тест — `bot.delete_message`
  бросает исключение (сообщение уже удалено вручную) — БД всё равно
  чистится, ответ всё равно "Опрос удалён."
- `tests/test_handlers_voting.py`: новый тест — `fake_bot.edit_message_text`
  бросает `TelegramBadRequest(method=..., message="Bad Request: message
  to edit not found")` → после вызова `handle_vote_toggle` опрос в БД
  имеет `status == "orphaned"`; голос при этом всё равно засчитан
  (записан в БД до попытки редактирования сообщения, как и сейчас).
- `tests/test_handlers_admin_edit.py`: аналогичный тест для одного из
  `apply_new_text`/`apply_new_date`/`_apply_delete` (например
  `apply_new_text`) — тот же `TelegramBadRequest` → `status ==
  "orphaned"`, при этом ответ админу остаётся `_PARTIAL_FAILURE_MESSAGE`
  (поведение ответа не меняется, меняется только сторонний эффект в БД).
