import pytest

from bot.config import load_config


def test_load_config_reads_env(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("BOT_TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("REMINDER_TIME", "19:00")
    monkeypatch.setenv("DB_PATH", "test.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "test_jobs.sqlite3")
    monkeypatch.setenv("THRESHOLD_DEBOUNCE_SECONDS", "10")

    config = load_config()

    assert config.bot_token == "test-token"
    assert config.admin_id == 42
    assert config.admin_username == "admin_user"
    assert config.timezone.key == "Europe/Moscow"
    assert config.reminder_hour == 19
    assert config.reminder_minute == 0
    assert config.db_path == "test.sqlite3"
    assert config.jobs_db_path == "test_jobs.sqlite3"
    assert config.threshold_debounce_seconds == 10


def test_load_config_missing_token_raises(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")

    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        load_config()


def test_load_config_defaults_threshold_debounce_seconds_to_900(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.delenv("THRESHOLD_DEBOUNCE_SECONDS", raising=False)

    config = load_config()

    assert config.threshold_debounce_seconds == 900


def test_relative_db_paths_resolve_under_data_dir(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("DATA_DIR", "/app/data")
    monkeypatch.setenv("DB_PATH", "poll_bot.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "jobs.sqlite3")

    config = load_config()

    import os
    assert config.db_path == os.path.join("/app/data", "poll_bot.sqlite3")
    assert config.jobs_db_path == os.path.join("/app/data", "jobs.sqlite3")


def test_absolute_db_paths_are_left_unchanged(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("DATA_DIR", "/app/data")
    monkeypatch.setenv("DB_PATH", "/somewhere/else/poll.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "/somewhere/else/jobs.sqlite3")

    config = load_config()

    assert config.db_path == "/somewhere/else/poll.sqlite3"
    assert config.jobs_db_path == "/somewhere/else/jobs.sqlite3"


def test_relative_db_paths_unchanged_without_data_dir(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("DB_PATH", "poll_bot.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "jobs.sqlite3")

    config = load_config()

    assert config.db_path == "poll_bot.sqlite3"
    assert config.jobs_db_path == "jobs.sqlite3"
