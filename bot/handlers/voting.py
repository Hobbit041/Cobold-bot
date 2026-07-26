from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.exc import IntegrityError

from bot import formatting, keyboards, repo, threshold_logic
from bot.scheduler import cancel_threshold_check, schedule_threshold_check, threshold_job_id

logger = logging.getLogger(__name__)

router = Router(name="voting")


@router.callback_query(F.data.startswith("vote:"))
async def handle_vote_toggle(
    callback: CallbackQuery,
    session_maker,
    scheduler,
    bot: Bot,
    admin_mention: str,
    threshold_check_callback,
    threshold_debounce_seconds: int,
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
        voter_mentions_by_option = {
            opt.id: [
                formatting.voter_mention(v.username, v.first_name)
                for v in await repo.get_voters(session, opt.id)
            ]
            for opt in poll_options
        }
        option_text = option.text
        option_date = option.date

    lines = [
        formatting.format_option_line(
            i + 1, opt.text, opt.date, counts[opt.id], voter_mentions_by_option[opt.id]
        )
        for i, opt in enumerate(poll_options)
    ]
    text = formatting.poll_message_text(poll.title, lines)
    keyboard = keyboards.build_poll_keyboard(
        [(opt.id, opt.text, opt.date, counts[opt.id]) for opt in poll_options]
    )
    try:
        await bot.edit_message_text(
            chat_id=poll.chat_id, message_id=poll.message_id, text=text, reply_markup=keyboard
        )
    except Exception as exc:
        if isinstance(exc, TelegramBadRequest) and "not found" in exc.message.lower():
            async with session_maker() as session:
                await repo.mark_poll_orphaned(session, poll.id)
        # The vote is already committed; a stale/undeletable poll message
        # shouldn't block threshold bookkeeping or leave the tapper without
        # a response below.
        logger.exception("Failed to refresh poll message for poll %s", poll.id)

    timer_pending = scheduler.get_job(threshold_job_id(option_id)) is not None
    action = threshold_logic.decide_action_after_vote_change(new_count, announced, timer_pending)

    if action == threshold_logic.SCHEDULE_TIMER:
        schedule_threshold_check(
            scheduler, option_id, threshold_check_callback, delay_seconds=threshold_debounce_seconds
        )
    elif action == threshold_logic.CANCEL_TIMER:
        cancel_threshold_check(scheduler, option_id)
    elif action == threshold_logic.ANNOUNCE_DROP:
        async with session_maker() as session:
            await repo.set_announced(session, option_id, False)
        try:
            await bot.send_message(
                chat_id=poll.chat_id,
                text=formatting.threshold_dropped_text(option_text, option_date),
                message_thread_id=poll.message_thread_id,
            )
        except Exception:
            logger.exception("Failed to send threshold-drop message for option %s", option_id)

    await callback.answer("Голос учтён!" if voted_now else "Голос снят.")
