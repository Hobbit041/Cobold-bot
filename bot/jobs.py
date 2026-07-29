from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey

from bot import formatting, repo, threshold_logic

logger = logging.getLogger(__name__)

DIALOG_TIMEOUT_MESSAGE = "Диалог отменён: не было ответа 5 минут."


@dataclass
class _Context:
    bot: object = None
    session_maker: object = None
    admin_mention: str = ""
    timezone: ZoneInfo | None = None
    storage: object = None


_context = _Context()

# Tasks currently executing check_threshold/send_due_reminders. main.py awaits
# these before disposing the DB engine on shutdown, since APScheduler's
# AsyncIOExecutor cancels in-flight coroutine jobs rather than waiting for
# them despite the scheduler's wait=True default.
in_flight_jobs: set[asyncio.Task] = set()


def configure(
    bot, session_maker, admin_mention: str, timezone: ZoneInfo, storage=None
) -> None:
    """Set the bot/session_maker/config used by the module-level job callbacks below.

    Must be called once at startup before scheduling any job that references
    check_threshold, send_due_reminders, or expire_dialog. These callbacks are
    deliberately plain module-level functions, not closures returned by a factory:
    APScheduler's SQLAlchemyJobStore persists jobs by pickling a reference to the
    callable (plus any bound `self`), and neither a nested closure nor an aiogram
    Bot/DB session factory baked into one is something that reference can resolve
    or that should be pickled. Reading shared state from this module-level context
    instead keeps the scheduled callables trivially picklable by qualified name.

    `storage` is the Dispatcher's FSM storage, needed only by expire_dialog to
    look up/clear a stuck admin dialog's state by (chat_id, user_id).
    """
    _context.bot = bot
    _context.session_maker = session_maker
    _context.admin_mention = admin_mention
    _context.timezone = timezone
    _context.storage = storage


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
            if option.date is None:
                return

            count = await repo.get_vote_count(session, option_id)
            if not threshold_logic.should_announce_on_timer_fire(count):
                return

            poll = await repo.get_poll(session, option.poll_id)
            chat_id = poll.chat_id
            message_thread_id = poll.message_thread_id
            option_text = option.text
            option_date = option.date

        # Send before persisting `announced`, so a failed send leaves the
        # option eligible to be re-announced on a future vote instead of
        # silently marking it announced when the chat never saw the message.
        await bot.send_message(
            chat_id=chat_id,
            text=formatting.threshold_reached_text(admin_mention, option_text, option_date),
            message_thread_id=message_thread_id,
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
                to_send.append(
                    (poll.chat_id, poll.message_thread_id, option.id, option.date, mentions)
                )

        for chat_id, message_thread_id, option_id, option_date, mentions in to_send:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=formatting.reminder_text(option_date, mentions),
                    message_thread_id=message_thread_id,
                )
            except Exception:
                logger.exception("Failed to send reminder for option %s in chat %s", option_id, chat_id)
                continue

            async with session_maker() as session:
                await repo.set_reminder_sent(session, option_id, True)
    finally:
        in_flight_jobs.discard(task)


async def delete_message(chat_id: int, message_id: int) -> None:
    """Delete a bot message, scheduled to run some delay after it was sent.

    Backs bot.scheduler.schedule_message_deletion so transient confirmations
    auto-expire instead of lingering in group chats. A plain module-level
    function (reading the bot from the shared context) so APScheduler's
    SQLAlchemyJobStore can pickle it by qualified name, like the other jobs
    here. Failures are swallowed: the message may already be gone (admin
    deleted it by hand) or the API call may transiently fail, and neither
    should crash the executor.
    """
    task = asyncio.current_task()
    in_flight_jobs.add(task)
    try:
        bot = _context.bot
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.exception("Failed to auto-delete message %s in chat %s", message_id, chat_id)
    finally:
        in_flight_jobs.discard(task)


async def expire_dialog(chat_id: int, user_id: int, message_thread_id: int | None) -> None:
    """Force-exit a stuck /newpoll or /editpoll dialog after 5 minutes of silence.

    Scheduled/cancelled from bot.handlers.dialog_cleanup on every dialog step in
    group chats, so an admin who abandons a dialog mid-flow (or who never sees
    the prompt) doesn't have every subsequent message in that chat swallowed and
    rejected forever as invalid input to a dialog they've forgotten about.
    """
    task = asyncio.current_task()
    in_flight_jobs.add(task)
    try:
        bot = _context.bot
        storage = _context.storage

        key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=user_id)
        fsm = FSMContext(storage=storage, key=key)

        if await fsm.get_state() is None:
            return

        data = await fsm.get_data()
        last_bot_message_id = data.get("last_bot_message_id")
        await fsm.clear()

        if last_bot_message_id is not None:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=last_bot_message_id)
            except Exception:
                logger.exception(
                    "Failed to delete last prompt %s while expiring dialog in chat %s",
                    last_bot_message_id,
                    chat_id,
                )

        try:
            await bot.send_message(
                chat_id=chat_id, text=DIALOG_TIMEOUT_MESSAGE, message_thread_id=message_thread_id
            )
        except Exception:
            logger.exception("Failed to send dialog-timeout notice in chat %s", chat_id)
    finally:
        in_flight_jobs.discard(task)
