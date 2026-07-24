from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger


def create_scheduler(jobs_db_path: str, timezone: ZoneInfo) -> AsyncIOScheduler:
    """Build and start an AsyncIOScheduler backed by a persistent SQLite job store.

    The scheduler is started immediately (rather than left in APScheduler's
    default "stopped" state) because APScheduler only performs real job-store
    writes -- and therefore only computes `next_run_time` and honors
    `replace_existing` dedup -- once its internal state has left STOPPED.
    While stopped, `add_job` merely appends to an in-memory pending list with
    no dedup and no `next_run_time`, which is unsuitable even for callers that
    only want to register/inspect/cancel jobs without the scheduler actually
    firing them yet (e.g. this module's own test suite).

    If called from within a running asyncio event loop (the normal case at
    bot startup), that loop is reused so scheduled jobs actually fire once the
    loop runs. Otherwise (e.g. plain synchronous test code) a private,
    never-run event loop is created just so the scheduler can leave the
    STOPPED state safely -- jobs added in that context are registered and
    queryable but will not actually execute, which is fine for tests that
    only exercise scheduling/cancellation bookkeeping.

    Callers must NOT call `.start()` again on the returned scheduler.

    Note: `.shutdown()` is likewise inert on a scheduler built from a
    synchronous caller (the throwaway-loop branch above) -- it only enqueues
    cleanup on the loop via `call_soon_threadsafe`, and since that loop is
    never run, the enqueued callback never executes and the job store never
    actually releases its connection. This is harmless for short-lived test
    processes but is a footgun for anyone adding explicit teardown later.
    """
    jobstore = SQLAlchemyJobStore(url=f"sqlite:///{jobs_db_path}")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(
        jobstores={"default": jobstore}, timezone=timezone, event_loop=loop
    )
    scheduler.start()
    return scheduler


def threshold_job_id(option_id: int) -> str:
    return f"threshold_check:{option_id}"


def schedule_threshold_check(
    scheduler: AsyncIOScheduler, option_id: int, callback, delay_minutes: int = 15
) -> None:
    run_date = dt.datetime.now(scheduler.timezone) + dt.timedelta(minutes=delay_minutes)
    scheduler.add_job(
        callback,
        trigger=DateTrigger(run_date=run_date),
        args=[option_id],
        id=threshold_job_id(option_id),
        replace_existing=True,
    )


def cancel_threshold_check(scheduler: AsyncIOScheduler, option_id: int) -> None:
    job_id = threshold_job_id(option_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def schedule_daily_reminder_job(scheduler: AsyncIOScheduler, callback, hour: int, minute: int) -> None:
    scheduler.add_job(
        callback,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_reminder_check",
        replace_existing=True,
    )
