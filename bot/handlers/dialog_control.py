"""/cancel: the admin's escape hatch out of a stuck /newpoll or /editpoll dialog.

Must be included in the Dispatcher before admin_create/admin_edit's routers
(see bot/main.py) -- those routers have catch-all message handlers per FSM
state with no Command filter, so without this router matching first, "/cancel"
typed mid-dialog would itself be swallowed as if it were poll title/option/etc
text instead of being recognized as a request to exit.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.dialog_cleanup import cleanup_and_finish

router = Router(name="dialog_control")


def _is_admin(message: Message, admin_id: int) -> bool:
    return message.from_user is not None and message.from_user.id == admin_id


@router.message(Command("cancel"))
async def cancel_dialog(message: Message, state: FSMContext, admin_id: int, scheduler=None) -> None:
    if not _is_admin(message, admin_id):
        await cleanup_and_finish(
            message, state, "Эта команда доступна только администратору.", scheduler=scheduler
        )
        return

    if await state.get_state() is None:
        await cleanup_and_finish(message, state, "Нечего отменять.", scheduler=scheduler)
        return

    await cleanup_and_finish(message, state, "Действие отменено.", scheduler=scheduler)
