# bot/main.py
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_config
from bot.db import create_engine_and_sessionmaker, init_db
from bot.handlers import admin_create, admin_edit, voting
from bot.jobs import make_daily_reminder_callback, make_threshold_check_callback
from bot.scheduler import create_scheduler, schedule_daily_reminder_job


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    engine, session_maker = create_engine_and_sessionmaker(config.db_path)
    await init_db(engine)

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_create.router)
    dp.include_router(admin_edit.router)
    dp.include_router(voting.router)

    scheduler = create_scheduler(config.jobs_db_path, config.timezone)
    admin_mention = f"@{config.admin_username}"

    threshold_check_callback = make_threshold_check_callback(bot, session_maker, admin_mention)
    daily_reminder_callback = make_daily_reminder_callback(bot, session_maker, config.timezone)
    schedule_daily_reminder_job(
        scheduler, daily_reminder_callback, config.reminder_hour, config.reminder_minute
    )

    try:
        await dp.start_polling(
            bot,
            session_maker=session_maker,
            scheduler=scheduler,
            admin_mention=admin_mention,
            admin_id=config.admin_id,
            threshold_check_callback=threshold_check_callback,
        )
    finally:
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
