# /checkme — список своих записей во всех чатах — дизайн

Дата: 2026-08-22

## Назначение

Пользователь голосует за варианты (даты игр) в разных чатах/темах, где
работает бот, и со временем теряет из виду, где и на что он записан.
`/checkme` — команда без ограничения доступа (доступна любому, не
только админу): показывает вызвавшему её пользователю все его текущие
записи (голоса) во **всех** чатах бота, а не только в том, где команда
вызвана. Каждая запись — кликабельная ссылка на исходное сообщение
опроса.

Ответ уходит прямо в чат, где вызвали команду (не в личку) — осознанно
принятый компромисс: список может содержать чаты, отличные от текущего.

## Формат ответа

```
Иван, вы записаны:
1. 22 августа, Настолки (Компания А)
2. 5 сентября, Покатушки (Компания Б)
```

где «22 августа, Настолки» — кликабельная ссылка на сообщение опроса в
чате «Компания А». Если у пользователя нет ни одной подходящей записи:
`"Иван, у вас нет записей на игры."`.

Это первое сообщение в проекте, отправляемое с `parse_mode="HTML"`
(остальной код намеренно нигде не задаёт `parse_mode` — заголовки
опросов/тексты вариантов/имена нигде не экранируются). Здесь HTML
включается точечно, только для этого сообщения, и весь
пользовательский текст, попадающий внутрь, экранируется через
`html.escape` — см. «Реализация».

## Какие записи попадают в список и в каком порядке

- Только варианты **с датой** (`Option.date is not None`). Варианты без
  даты в список не попадают вовсе (не просто без даты в строке — вся
  запись пропускается).
- Только неудалённые варианты (`Option.is_deleted == False`).
- Опросы в статусе `active` и `orphaned` — оба показываются наравне
  (orphaned не отфильтровывается: ссылка может как открыться, так и
  нет — это решает Telegram на своей стороне).
- Сортировка: по дате варианта по возрастанию (ближайшая игра первой),
  при равенстве дат — по `chat_id`, затем по `position` варианта (для
  детерминизма).
- Запись пропускается целиком, если для неё не удалось построить
  рабочую ссылку (см. ниже) — без запасного варианта в духе «покажем
  через id чата».

## Реализация

### `bot/repo.py`

Новая функция:

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

### `bot/formatting.py`

Вся сборка HTML-текста и экранирование остаются в одном месте, рядом с
остальными текстовыми шаблонами:

- `build_message_link(chat_id: int, message_id: int, username: str | None) -> str | None`
  — `https://t.me/{username}/{message_id}`, если у чата есть публичный
  username; иначе `https://t.me/c/{internal_id}/{message_id}`, если
  `chat_id` начинается с `-100` (супергруппа/канал, `internal_id` —
  строка `chat_id` без префикса `-100`); иначе `None` (обычная, не
  супергруппа, группа без username — рабочую ссылку построить нельзя).
- `checkme_line(index: int, option_text: str, option_date: dt.date, chat_title: str, link: str) -> str`
  → `` `1. <a href="...">22 августа, Текст</a> (Название чата)` `` —
  ссылкой становится только «дата, текст»; `option_text`, `chat_title`
  и `link` экранируются через `html.escape`.
- `checkme_header(mention: str) -> str` → `"{mention}, вы записаны:"`,
  `mention` экранирован.
- `checkme_empty_text(mention: str) -> str` → `"{mention}, у вас нет записей на игры."`,
  `mention` экранирован.

### Новый `bot/handlers/checkme.py`

```python
router = Router(name="checkme")

@router.message(Command("checkme"))
async def handle_checkme(message: Message, bot: Bot, session_maker) -> None:
    ...
```

Без проверки на админа (`_is_admin` не вызывается). Поток:

1. `user = message.from_user`; если `None` — тихо выходим (не может
   быть текстовой команды без отправителя).
2. Забираем `rows = await repo.get_votes_by_user(session, user.id)`.
3. Для каждой `(poll, option)`:
   - если `poll.message_id is None` — пропустить (защитная проверка,
     штатно такого быть не должно: `create_and_publish_poll` откатывает
     `Poll`, если отправка сообщения не удалась);
   - резолвим `Chat` через `bot.get_chat(poll.chat_id)`, кэшируя
     результат по `chat_id` в `dict` на время вызова (несколько строк
     часто ссылаются на один и тот же чат); при исключении — кэшируем
     `None` и пропускаем строку;
   - если `chat is None` или `not chat.title` — пропустить;
   - `link = formatting.build_message_link(poll.chat_id, poll.message_id, chat.username)`;
     если `None` — пропустить;
   - иначе — `formatting.checkme_line(len(lines) + 1, option.text, option.date, chat.title, link)`
     добавляется в список строк.
4. Если строк нет — `await message.answer(formatting.checkme_empty_text(mention))`
   (без `parse_mode`, экранирование там не нужно чувствительно, но
   `checkme_empty_text` всё равно экранирует для единообразия).
5. Иначе — `text = formatting.checkme_header(mention) + "\n" + "\n".join(lines)`,
   `await message.answer(text, parse_mode="HTML")`.
6. `mention = formatting.voter_mention(user.username, user.first_name)`
   (переиспользуем существующую функцию).

Явный `message_thread_id` не передаётся — `Message.answer()` в aiogram
уже сам отвечает в ту же тему, если исходное сообщение было отправлено
в теме (тот же идиом, что использует `dialog_cleanup.cleanup_and_answer`
для группового случая).

### `bot/main.py`

- `from bot.handlers import admin_copy, admin_create, admin_delete, admin_edit, checkme, dialog_control, voting`
- `dp.include_router(checkme.router)` — порядок относительно других
  роутеров не важен: `/checkme` не участвует ни в одном FSM и не
  пересекается по фильтрам ни с одним существующим состоянием.

### Не входит в объём

Пагинация длинных списков (Telegram режет сообщения на ~4096
символов) не реализуется — при текущем масштабе бота (см. существующие
комментарии в кодовой базе про admin dialog storage) вероятность
упереться в лимit крайне мала. Если пользователь упрётся в лимит,
`message.answer` вернёт ошибку Telegram API, необработанного падения
бота при этом не произойдёт (ошибка останется в логах хендлера).

## Тестирование

- `tests/test_repo_voting.py`: тесты на `get_votes_by_user` —
  фильтрация по `user_id` (голос другого пользователя не попадает),
  фильтрация удалённых опций, фильтрация опций без даты, сортировка по
  дате при нескольких опросах/чатах.
- `tests/test_formatting.py`: `build_message_link` — публичный
  username, `-100`-супергруппа без username, обычная группа без
  username (`None`); `checkme_line`/`checkme_header`/`checkme_empty_text`
  — корректное экранирование спецсимволов в тексте варианта/названии
  чата/имени пользователя.
- Новый `tests/test_handlers_checkme.py`, по образцу
  `test_handlers_voting.py` (`FakeUser`, `AsyncMock` для `bot`,
  `session_maker` из `conftest.py`):
  - создать несколько опросов/опций в разных чатах, проголосовать от
    имени пользователя и от чужого имени, вызвать хендлер, проверить
    итоговый текст и порядок строк;
  - `bot.get_chat` бросает исключение для одного из чатов — эта строка
    пропущена, остальные остались;
  - `bot.get_chat` возвращает чат без `username`, `chat_id` не
    супергрупповой (`-100...`) — строка пропущена;
  - опция без даты — не попадает в список;
  - у пользователя нет голосов — отправляется `checkme_empty_text`.
