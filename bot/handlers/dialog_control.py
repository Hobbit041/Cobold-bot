"""/cancel: escape hatch out of a stuck /newpoll or /editpoll dialog.

Must be included in the Dispatcher before admin_create/admin_edit/admin_copy/admin_delete's routers
(see bot/main.py) -- those routers have catch-all message handlers per FSM
state with no Command filter, so without this router matching first, "/cancel"
typed mid-dialog would itself be swallowed as if it were poll title/option/etc
text instead of being recognized as a request to exit.

No authorization check is needed here: aiogram's FSM state is already scoped
to (chat_id, user_id), so /cancel can only ever clear the caller's own dialog.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.dialog_cleanup import cleanup_and_finish

router = Router(name="dialog_control")


@router.message(Command("cancel"))
async def cancel_dialog(message: Message, state: FSMContext, scheduler=None) -> None:
    if await state.get_state() is None:
        await cleanup_and_finish(message, state, "Нечего отменять.", scheduler=scheduler)
        return

    await cleanup_and_finish(message, state, "Действие отменено.", scheduler=scheduler)
