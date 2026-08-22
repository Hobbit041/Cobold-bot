from unittest.mock import AsyncMock

from bot.authz import filter_by_chat_admin, is_chat_admin


class FakeChatMember:
    def __init__(self, status):
        self.status = status


async def test_is_chat_admin_true_for_administrator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="administrator")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is True


async def test_is_chat_admin_true_for_creator():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="creator")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is True


async def test_is_chat_admin_false_for_plain_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = FakeChatMember(status="member")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is False


async def test_is_chat_admin_false_when_lookup_raises():
    bot = AsyncMock()
    bot.get_chat_member.side_effect = RuntimeError("bot not in chat")

    assert await is_chat_admin(bot, chat_id=-500, user_id=1) is False


async def test_filter_by_chat_admin_keeps_only_administered_chats():
    bot = AsyncMock()

    async def _get_chat_member(chat_id, user_id):
        statuses = {-1: "administrator", -2: "member"}
        return FakeChatMember(status=statuses[chat_id])

    bot.get_chat_member.side_effect = _get_chat_member
    items = [("a", -1), ("b", -2), ("c", -1)]

    kept = await filter_by_chat_admin(bot, items, user_id=7, chat_id_getter=lambda x: x[1])

    assert kept == [("a", -1), ("c", -1)]
    assert bot.get_chat_member.await_count == 2  # one call per distinct chat_id, cached


async def test_filter_by_chat_admin_returns_empty_for_missing_user_id():
    bot = AsyncMock()

    kept = await filter_by_chat_admin(bot, [("a", -1)], user_id=None, chat_id_getter=lambda x: x[1])

    assert kept == []
    bot.get_chat_member.assert_not_awaited()
