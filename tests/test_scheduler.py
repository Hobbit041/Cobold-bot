from zoneinfo import ZoneInfo

from bot.scheduler import (
    cancel_dialog_timeout,
    cancel_threshold_check,
    create_scheduler,
    dialog_timeout_job_id,
    schedule_daily_reminder_job,
    schedule_dialog_timeout,
    schedule_threshold_check,
    threshold_job_id,
)


def _noop(option_id):
    pass


def _noop_daily():
    pass


def _noop_dialog_timeout(chat_id, user_id, message_thread_id):
    pass


def test_schedule_threshold_check_creates_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_seconds=900)

    job = scheduler.get_job(threshold_job_id(1))
    assert job is not None


def test_schedule_threshold_check_replaces_existing_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_seconds=900)
    first_run_time = scheduler.get_job(threshold_job_id(1)).next_run_time

    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_seconds=1200)
    second_run_time = scheduler.get_job(threshold_job_id(1)).next_run_time

    assert len(scheduler.get_jobs()) == 1
    assert second_run_time > first_run_time


def test_cancel_threshold_check_removes_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    schedule_threshold_check(scheduler, option_id=1, callback=_noop, delay_seconds=900)

    cancel_threshold_check(scheduler, option_id=1)

    assert scheduler.get_job(threshold_job_id(1)) is None


def test_cancel_threshold_check_noop_when_no_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    cancel_threshold_check(scheduler, option_id=999)


def test_schedule_daily_reminder_job_creates_cron_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_daily_reminder_job(scheduler, callback=_noop_daily, hour=19, minute=0)

    job = scheduler.get_job("daily_reminder_check")
    assert job is not None


def test_schedule_dialog_timeout_creates_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_dialog_timeout(
        scheduler, chat_id=-100, user_id=1, message_thread_id=42, callback=_noop_dialog_timeout
    )

    job = scheduler.get_job(dialog_timeout_job_id(-100, 1))
    assert job is not None
    assert job.args == (-100, 1, 42)


def test_schedule_dialog_timeout_replaces_existing_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    schedule_dialog_timeout(
        scheduler, chat_id=-100, user_id=1, message_thread_id=None, callback=_noop_dialog_timeout, delay_seconds=300
    )
    first_run_time = scheduler.get_job(dialog_timeout_job_id(-100, 1)).next_run_time

    schedule_dialog_timeout(
        scheduler, chat_id=-100, user_id=1, message_thread_id=None, callback=_noop_dialog_timeout, delay_seconds=600
    )
    second_run_time = scheduler.get_job(dialog_timeout_job_id(-100, 1)).next_run_time

    assert len(scheduler.get_jobs()) == 1
    assert second_run_time > first_run_time


def test_cancel_dialog_timeout_removes_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))
    schedule_dialog_timeout(
        scheduler, chat_id=-100, user_id=1, message_thread_id=None, callback=_noop_dialog_timeout
    )

    cancel_dialog_timeout(scheduler, chat_id=-100, user_id=1)

    assert scheduler.get_job(dialog_timeout_job_id(-100, 1)) is None


def test_cancel_dialog_timeout_noop_when_no_job(tmp_path):
    scheduler = create_scheduler(str(tmp_path / "jobs.sqlite3"), ZoneInfo("Europe/Moscow"))

    cancel_dialog_timeout(scheduler, chat_id=-100, user_id=999)
