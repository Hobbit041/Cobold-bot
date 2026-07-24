# bot/main.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from bot import jobs
from bot.config import load_config
from bot.db import create_engine_and_sessionmaker, init_db
from bot.handlers import admin_create, admin_edit, voting
from bot.scheduler import create_scheduler, schedule_daily_reminder_job


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Populates os.environ from a .env file in the working directory, if present.
    # Only fills in variables not already set, so it's a no-op under systemd
    # deployments where EnvironmentFile= has already loaded them directly.
    load_dotenv()
    config = load_config()

    engine, session_maker = create_engine_and_sessionmaker(config.db_path)
    await init_db(engine)

    # No parse_mode is set: no formatting function anywhere in this codebase emits
    # HTML/Markdown, and poll titles/option text/participant names are untrusted
    # user input passed straight through -- setting a parse mode without escaping
    # that input would make Telegram reject messages containing plain "&"/"<"/">"
    # (e.g. a poll titled "Coffee & Games", or a voter whose display name has one).
    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())  # in-process only; a restart mid-flow silently drops admin conversation state -- acceptable at this bot's scale
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(voting.router)

    scheduler = create_scheduler(config.jobs_db_path, config.timezone)
    admin_mention = f"@{config.admin_username}"

    # jobs.check_threshold/jobs.send_due_reminders are plain module-level functions
    # (not closures) so APScheduler's SQLAlchemyJobStore can reference them by
    # qualified name -- configure() sets the bot/session_maker/etc. they read from
    # a shared module-level context instead of baking live resources into a closure.
    jobs.configure(bot, session_maker, admin_mention, config.timezone)
    schedule_daily_reminder_job(
        scheduler, jobs.send_due_reminders, config.reminder_hour, config.reminder_minute
    )

    try:
        await dp.start_polling(
            bot,
            session_maker=session_maker,
            scheduler=scheduler,
            admin_mention=admin_mention,
            admin_id=config.admin_id,
            threshold_check_callback=jobs.check_threshold,
            threshold_debounce_seconds=config.threshold_debounce_seconds,
        )
    finally:
        # AsyncIOScheduler.shutdown() defers to a call_soon_threadsafe callback, and
        # AsyncIOExecutor.shutdown() cancels in-flight coroutine jobs rather than
        # waiting for them (APScheduler's wait=True is not honored for async jobs).
        # jobs.check_threshold/send_due_reminders track their own in-flight tasks;
        # await them here before disposing the DB engine they depend on, so a job
        # mid-flight at shutdown time doesn't race a closing connection pool.
        scheduler.shutdown()
        if jobs.in_flight_jobs:
            await asyncio.gather(*jobs.in_flight_jobs, return_exceptions=True)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
