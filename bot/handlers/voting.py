from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.exc import IntegrityError

from bot import formatting, keyboards, repo, threshold_logic
from bot.scheduler import cancel_threshold_check, schedule_threshold_check

router = Router(name="voting")


@router.callback_query(F.data.startswith("vote:"))
async def handle_vote_toggle(
    callback: CallbackQuery,
    session_maker,
    scheduler,
    bot: Bot,
    admin_mention: str,
    threshold_check_callback,
) -> None:
    option_id = int(callback.data.split(":", 1)[1])
    user = callback.from_user

    async with session_maker() as session:
        option = await session.get(repo.Option, option_id)
        if option is None or option.is_deleted:
            await callback.answer("Этот вариант больше недоступен.", show_alert=True)
            return

        try:
            voted_now, new_count = await repo.toggle_vote(
                session, option_id, user_id=user.id, username=user.username, first_name=user.first_name
            )
        except IntegrityError:
            # Two rapid taps on the same button dispatched two concurrent
            # CallbackQuery updates: both saw "no existing vote" before
            # either committed, so the loser's insert violated the
            # uq_vote_option_user unique constraint. The vote clearly
            # already exists thanks to the winner -- recover gracefully
            # instead of letting the exception crash the handler.
            await session.rollback()
            await callback.answer("Голос уже учтён, обновите через секунду.")
            return

        announced = await repo.is_announced(session, option_id)
        poll_options = await repo.get_poll_options(session, option.poll_id)
        poll = await repo.get_poll(session, option.poll_id)

        counts = {opt.id: await repo.get_vote_count(session, opt.id) for opt in poll_options}
        option_text = option.text

    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, counts[opt.id]) for opt in poll_options]
    )
    await bot.edit_message_reply_markup(
        chat_id=poll.chat_id, message_id=poll.message_id, reply_markup=keyboard
    )

    action = threshold_logic.decide_action_after_vote_change(new_count, announced)

    if action == threshold_logic.SCHEDULE_TIMER:
        schedule_threshold_check(scheduler, option_id, threshold_check_callback, delay_minutes=15)
    elif action == threshold_logic.CANCEL_TIMER:
        cancel_threshold_check(scheduler, option_id)
    elif action == threshold_logic.ANNOUNCE_DROP:
        async with session_maker() as session:
            await repo.set_announced(session, option_id, False)
        await bot.send_message(chat_id=poll.chat_id, text=formatting.threshold_dropped_text(option_text))

    await callback.answer("Голос учтён!" if voted_now else "Голос снят.")
