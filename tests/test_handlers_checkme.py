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
