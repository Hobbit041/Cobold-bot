from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from bot import formatting, repo, threshold_logic


def make_threshold_check_callback(bot, session_maker, admin_mention: str):
    async def check_threshold(option_id: int) -> None:
        async with session_maker() as session:
            option = await session.get(repo.Option, option_id)
            if option is None or option.is_deleted:
                return

            count = await repo.get_vote_count(session, option_id)
            if not threshold_logic.should_announce_on_timer_fire(count):
                return

            await repo.set_announced(session, option_id, True)
            poll = await repo.get_poll(session, option.poll_id)
            chat_id = poll.chat_id
            option_text = option.text

        await bot.send_message(
            chat_id=chat_id, text=formatting.threshold_reached_text(admin_mention, option_text)
        )

    return check_threshold


def make_daily_reminder_callback(bot, session_maker, timezone: ZoneInfo):
    async def send_due_reminders() -> None:
        today = dt.datetime.now(timezone).date()
        tomorrow = today + dt.timedelta(days=1)

        async with session_maker() as session:
            due_options = await repo.get_options_due_for_reminder(session, tomorrow)
            to_send = []
            for option in due_options:
                voters = await repo.get_voters(session, option.id)
                mentions = [formatting.voter_mention(v.username, v.first_name) for v in voters]
                poll = await repo.get_poll(session, option.poll_id)
                to_send.append((poll.chat_id, option.id, option.date, mentions))

            for chat_id, option_id, option_date, mentions in to_send:
                await bot.send_message(chat_id=chat_id, text=formatting.reminder_text(option_date, mentions))
                await repo.set_reminder_sent(session, option_id, True)

    return send_due_reminders
