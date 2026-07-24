from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from bot import formatting, repo, threshold_logic

logger = logging.getLogger(__name__)


@dataclass
class _Context:
    bot: object = None
    session_maker: object = None
    admin_mention: str = ""
    timezone: ZoneInfo | None = None


_context = _Context()

# Tasks currently executing check_threshold/send_due_reminders. main.py awaits
# these before disposing the DB engine on shutdown, since APScheduler's
# AsyncIOExecutor cancels in-flight coroutine jobs rather than waiting for
# them despite the scheduler's wait=True default.
in_flight_jobs: set[asyncio.Task] = set()


def configure(bot, session_maker, admin_mention: str, timezone: ZoneInfo) -> None:
    """Set the bot/session_maker/config used by the module-level job callbacks below.

    Must be called once at startup before scheduling any job that references
    check_threshold or send_due_reminders. These callbacks are deliberately
    plain module-level functions, not closures returned by a factory: APScheduler's
    SQLAlchemyJobStore persists jobs by pickling a reference to the callable (plus
    any bound `self`), and neither a nested closure nor an aiogram Bot/DB session
    factory baked into one is something that reference can resolve or that should
    be pickled. Reading shared state from this module-level context instead keeps
    the scheduled callables trivially picklable by qualified name.
    """
    _context.bot = bot
    _context.session_maker = session_maker
    _context.admin_mention = admin_mention
    _context.timezone = timezone


async def check_threshold(option_id: int) -> None:
    task = asyncio.current_task()
    in_flight_jobs.add(task)
    try:
        bot = _context.bot
        session_maker = _context.session_maker
        admin_mention = _context.admin_mention

        async with session_maker() as session:
            option = await session.get(repo.Option, option_id)
            if option is None or option.is_deleted:
                return

            count = await repo.get_vote_count(session, option_id)
            if not threshold_logic.should_announce_on_timer_fire(count):
                return

            poll = await repo.get_poll(session, option.poll_id)
            chat_id = poll.chat_id
            option_text = option.text
            option_date = option.date

        # Send before persisting `announced`, so a failed send leaves the
        # option eligible to be re-announced on a future vote instead of
        # silently marking it announced when the chat never saw the message.
        await bot.send_message(
            chat_id=chat_id,
            text=formatting.threshold_reached_text(admin_mention, option_text, option_date),
        )

        async with session_maker() as session:
            await repo.set_announced(session, option_id, True)
    finally:
        in_flight_jobs.discard(task)


async def send_due_reminders() -> None:
    task = asyncio.current_task()
    in_flight_jobs.add(task)
    try:
        bot = _context.bot
        session_maker = _context.session_maker
        timezone = _context.timezone

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
            try:
                await bot.send_message(chat_id=chat_id, text=formatting.reminder_text(option_date, mentions))
            except Exception:
                logger.exception("Failed to send reminder for option %s in chat %s", option_id, chat_id)
                continue

            async with session_maker() as session:
                await repo.set_reminder_sent(session, option_id, True)
    finally:
        in_flight_jobs.discard(task)
