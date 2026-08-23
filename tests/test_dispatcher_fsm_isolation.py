"""Integration test: aiogram's FSMContext is isolated per (chat_id, user_id),
so one user's in-progress command dialog can never be advanced or hijacked by
a different user's message in the same chat.

Unlike the rest of this suite (which calls handler functions directly with a
manually-built FSMContext, bypassing aiogram's own dispatch layer), this test
feeds real Update objects through a real Dispatcher -- the isolation being
proven here is a property of aiogram's own FSMContextMiddleware/StorageKey
resolution (FSMStrategy.USER_IN_CHAT is aiogram's Dispatcher default, and
bot/main.py never overrides it), not of any of this bot's own handler code.
It's proven once here with a minimal throwaway router rather than duplicated
for every production command, since the guarantee is generic to the dispatch
mechanism every admin_* handler (newpoll/editpoll/deletepoll/copypoll) relies
on for its multi-step FSM dialogs, not specific to any one of them.
"""

from __future__ import annotations

import datetime as dt

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

# Well-formed but non-functional: extract_bot_id() only parses the numeric
# prefix, and no test here ever calls a real Bot API method, so this never
# needs to be a valid, authorized token.
_FAKE_TOKEN = "123456789:AAFakeTokenForTestsOnlyNeverUsedOverNetwork00"


class _ProbeStates(StatesGroup):
    waiting_reply = State()


def _build_dispatcher() -> tuple[Dispatcher, list[int]]:
    """A minimal two-step dialog: /begin arms waiting_reply, then any message
    while waiting is "handled" -- structurally the same shape as this bot's
    real /newpoll, /editpoll, /deletepoll, /copypoll flows (a command starts
    a dialog, then a bare reply like a poll number advances it).
    """
    router = Router(name="probe")
    handled_by: list[int] = []

    @router.message(Command("begin"))
    async def begin(message: Message, state: FSMContext) -> None:
        await state.set_state(_ProbeStates.waiting_reply)

    @router.message(_ProbeStates.waiting_reply)
    async def finish(message: Message, state: FSMContext) -> None:
        handled_by.append(message.from_user.id)
        await state.clear()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return dp, handled_by


def _message_update(update_id: int, user_id: int, chat_id: int, text: str) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=dt.datetime.now(dt.timezone.utc),
            chat=Chat(id=chat_id, type="supergroup"),
            from_user=User(id=user_id, is_bot=False, first_name="U"),
            text=text,
        ),
    )


async def test_one_users_dialog_state_cannot_be_advanced_by_another_users_message():
    dp, handled_by = _build_dispatcher()
    bot = Bot(token=_FAKE_TOKEN)
    chat_id = -500

    try:
        # User A starts a dialog (mirrors typing /newpoll, /editpoll, etc.)
        # and is now "waiting" for a reply.
        await dp.feed_update(bot, _message_update(1, user_id=100, chat_id=chat_id, text="/begin"))
        assert handled_by == []

        # A bystander (different user_id, same chat) sends a bare reply while
        # A's dialog is open -- e.g. someone else typing "1" in the group.
        # This must NOT be picked up as A's answer: B's own FSM state (never
        # touched) is still None, so B's message doesn't match the
        # waiting-state filter at all and is simply ignored.
        await dp.feed_update(bot, _message_update(2, user_id=200, chat_id=chat_id, text="1"))
        assert handled_by == []

        # A's own state is untouched by B's message and still resolves.
        a_state = dp.fsm.resolve_context(bot=bot, chat_id=chat_id, user_id=100)
        assert await a_state.get_state() == _ProbeStates.waiting_reply.state

        # A's own reply is correctly picked up.
        await dp.feed_update(bot, _message_update(3, user_id=100, chat_id=chat_id, text="1"))
        assert handled_by == [100]
    finally:
        await bot.session.close()


async def test_two_users_can_run_independent_dialogs_in_the_same_chat_concurrently():
    dp, handled_by = _build_dispatcher()
    bot = Bot(token=_FAKE_TOKEN)
    chat_id = -500

    try:
        # Both A and B start their own dialogs in the same chat...
        await dp.feed_update(bot, _message_update(1, user_id=100, chat_id=chat_id, text="/begin"))
        await dp.feed_update(bot, _message_update(2, user_id=200, chat_id=chat_id, text="/begin"))
        assert handled_by == []

        # ...and each only ever advances their own dialog, in either order.
        await dp.feed_update(bot, _message_update(3, user_id=200, chat_id=chat_id, text="reply"))
        assert handled_by == [200]

        await dp.feed_update(bot, _message_update(4, user_id=100, chat_id=chat_id, text="reply"))
        assert handled_by == [200, 100]
    finally:
        await bot.session.close()
