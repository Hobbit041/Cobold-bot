import datetime as dt
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from bot import keyboards, repo
from bot.date_utils import format_date_ru
from bot.handlers.games import handle_games

TZ = ZoneInfo("Europe/Moscow")


class FakeUser:
    def __init__(self, id, username, first_name):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeChat:
    def __init__(self, id, type):
        self.id = id
        self.type = type


class FakeMessage:
    def __init__(self, user, chat):
        self.from_user = user
        self.chat = chat
        self.message_id = 1
        self.message_thread_id = None
        self.answer = AsyncMock()
        self.delete = AsyncMock()


class FakeResolvedChat:
    def __init__(self, title, username=None):
        self.title = title
        self.username = username


class FakeChatMember:
    def __init__(self, status):
        self.status = status


async def _vote_n_times(session, option_id, count):
    for i in range(count):
        await repo.toggle_vote(session, option_id, user_id=1000 + i, username=f"u{i}", first_name=f"U{i}")


async def test_handle_games_lists_only_gathered_dated_options_in_this_chat(session_maker):
    today = dt.datetime.now(TZ).date()
    date_a = today + dt.timedelta(days=3)
    date_b = today + dt.timedelta(days=10)
    async with session_maker() as session:
        poll = await repo.create_poll(
            session,
            chat_id=555,
            title="Игра",
            options=[
                ("Собралось", date_a),
                ("Мало голосов", date_b),
                ("Без даты", None),
            ],
        )
        await repo.set_poll_message(session, poll.id, message_id=11)
        options = await repo.get_poll_options(session, poll.id)
        gathered_option, low_option, undated_option = options
        await _vote_n_times(session, gathered_option.id, 4)
        await _vote_n_times(session, low_option.id, 3)
        await _vote_n_times(session, undated_option.id, 5)

        other_poll = await repo.create_poll(
            session, chat_id=666, title="Другой чат", options=[("Тоже собралось", date_a)]
        )
        await repo.set_poll_message(session, other_poll.id, message_id=22)
        other_option = (await repo.get_poll_options(session, other_poll.id))[0]
        await _vote_n_times(session, other_option.id, 4)

    fake_bot = AsyncMock()
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Компания", username="company")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"), FakeChat(555, "group"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.delete.assert_awaited_once()
    message.answer.assert_awaited_once_with(
        "Собравшиеся игры:\n"
        f'1. <a href="https://t.me/company/11">{format_date_ru(date_a)}, Собралось</a> (Компания, 4 игрока)',
        parse_mode="HTML",
        reply_markup=keyboards.build_delete_keyboard(1),
    )
    fake_bot.get_chat.assert_awaited_once_with(555)


async def test_handle_games_empty_when_nothing_gathered(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username=None, first_name="Alice"), FakeChat(555, "supergroup"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "Пока нет собравшихся игр (нужно 4+ игрока на вариант с датой).",
        parse_mode="HTML",
        reply_markup=keyboards.build_delete_keyboard(1),
    )
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_games_refuses_in_dm_for_non_admin(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        poll = await repo.create_poll(session, chat_id=200, title="Игра", options=[("Собралось", today)])
        await repo.set_poll_message(session, poll.id, message_id=11)
        option = (await repo.get_poll_options(session, poll.id))[0]
        await _vote_n_times(session, option.id, 4)

    fake_bot = AsyncMock()
    fake_bot.get_chat_member.return_value = FakeChatMember(status="member")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"), FakeChat(1, "private"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "В личных сообщениях эта команда доступна только администраторам чатов "
        "с опросами — и покажет игры только из тех чатов, где вы администратор."
    )
    fake_bot.get_chat.assert_not_awaited()


async def test_handle_games_refuses_in_dm_when_no_polls_exist_anywhere(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"), FakeChat(1, "private"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "В личных сообщениях эта команда доступна только администраторам чатов "
        "с опросами — и покажет игры только из тех чатов, где вы администратор."
    )
    fake_bot.get_chat_member.assert_not_awaited()


async def test_handle_games_in_dm_shows_only_chats_user_administers(session_maker):
    today = dt.datetime.now(TZ).date()
    async with session_maker() as session:
        admin_poll = await repo.create_poll(
            session, chat_id=100, title="Игра A", options=[("Собралось А", today)]
        )
        await repo.set_poll_message(session, admin_poll.id, message_id=11)
        admin_option = (await repo.get_poll_options(session, admin_poll.id))[0]
        await _vote_n_times(session, admin_option.id, 4)

        other_poll = await repo.create_poll(
            session, chat_id=200, title="Игра B", options=[("Собралось Б", today)]
        )
        await repo.set_poll_message(session, other_poll.id, message_id=22)
        other_option = (await repo.get_poll_options(session, other_poll.id))[0]
        await _vote_n_times(session, other_option.id, 4)

    def _get_chat_member(chat_id, user_id):
        if chat_id == 100:
            return FakeChatMember(status="administrator")
        return FakeChatMember(status="member")

    fake_bot = AsyncMock()
    fake_bot.get_chat_member.side_effect = _get_chat_member
    fake_bot.get_chat.return_value = FakeResolvedChat(title="Компания А", username="companya")
    message = FakeMessage(FakeUser(id=1, username="alice", first_name="Alice"), FakeChat(1, "private"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.answer.assert_awaited_once_with(
        "Собравшиеся игры:\n"
        f'1. <a href="https://t.me/companya/11">{format_date_ru(today)}, Собралось А</a> (Компания А, 4 игрока)',
        parse_mode="HTML",
        reply_markup=keyboards.build_delete_keyboard(1),
    )
    fake_bot.get_chat.assert_awaited_once_with(100)


async def test_handle_games_deletes_triggering_command_message(session_maker):
    fake_bot = AsyncMock()
    message = FakeMessage(FakeUser(id=1, username=None, first_name="Alice"), FakeChat(555, "group"))

    await handle_games(message, bot=fake_bot, session_maker=session_maker)

    message.delete.assert_awaited_once()
