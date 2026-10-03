import datetime as dt
from unittest.mock import AsyncMock

from bot import links, repo


class FakeResolvedChat:
    def __init__(self, username=None):
        self.username = username


def _bot(usernames=None, error=None):
    bot = AsyncMock()
    usernames = usernames or {}

    async def _get_chat(chat_id):
        if error is not None:
            raise error
        return FakeResolvedChat(username=usernames.get(chat_id))

    bot.get_chat.side_effect = _get_chat
    return bot


async def _poll(session_maker, chat_id, message_id=None, orphaned=False, title="Игра"):
    async with session_maker() as session:
        poll = await repo.create_poll(
            session, chat_id=chat_id, title=title, options=[("24.07", dt.date(2026, 7, 24))]
        )
        if message_id is not None:
            await repo.set_poll_message(session, poll.id, message_id=message_id)
        if orphaned:
            await repo.mark_poll_orphaned(session, poll.id)
        return await repo.get_poll(session, poll.id)


async def test_poll_message_link_uses_the_private_supergroup_form(session_maker):
    assert await links.poll_message_link(_bot(), -1001234567890, 42) == (
        "https://t.me/c/1234567890/42"
    )


async def test_poll_message_link_uses_the_username_form_when_there_is_one(session_maker):
    bot = _bot(usernames={-1001234567890: "companya"})
    assert await links.poll_message_link(bot, -1001234567890, 42) == "https://t.me/companya/42"


async def test_poll_message_link_without_a_message_id_is_none(session_maker):
    bot = _bot()
    assert await links.poll_message_link(bot, -1001234567890, None) is None
    bot.get_chat.assert_not_awaited()


async def test_poll_message_link_falls_back_when_get_chat_fails(session_maker):
    bot = _bot(error=RuntimeError("bot was removed from chat"))
    assert await links.poll_message_link(bot, -1001234567890, 42) == (
        "https://t.me/c/1234567890/42"
    )


async def test_poll_message_link_is_none_for_a_basic_group(session_maker):
    """A plain group id has neither a /c/ form nor a username."""
    assert await links.poll_message_link(_bot(), -123456789, 42) is None


async def test_poll_message_links_maps_each_poll_by_id(session_maker):
    linked = await _poll(session_maker, chat_id=-1001234567890, message_id=42)
    no_message = await _poll(session_maker, chat_id=-1001234567890)
    orphaned = await _poll(session_maker, chat_id=-1001234567890, message_id=99, orphaned=True)

    result = await links.poll_message_links(_bot(), [linked, no_message, orphaned])

    assert result == {
        linked.id: "https://t.me/c/1234567890/42",
        no_message.id: None,
        orphaned.id: None,
    }


async def test_poll_message_links_looks_each_chat_up_once(session_maker):
    first = await _poll(session_maker, chat_id=-1001234567890, message_id=1)
    second = await _poll(session_maker, chat_id=-1001234567890, message_id=2)
    other_chat = await _poll(session_maker, chat_id=-1009876543210, message_id=3)

    bot = _bot()
    await links.poll_message_links(bot, [first, second, other_chat])

    assert bot.get_chat.await_count == 2
