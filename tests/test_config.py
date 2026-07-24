import pytest

from bot.config import load_config


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")
    monkeypatch.setenv("BOT_TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("REMINDER_TIME", "19:00")
    monkeypatch.setenv("DB_PATH", "test.sqlite3")
    monkeypatch.setenv("JOBS_DB_PATH", "test_jobs.sqlite3")

    config = load_config()

    assert config.bot_token == "test-token"
    assert config.admin_id == 42
    assert config.admin_username == "admin_user"
    assert config.timezone.key == "Europe/Moscow"
    assert config.reminder_hour == 19
    assert config.reminder_minute == 0
    assert config.db_path == "test.sqlite3"
    assert config.jobs_db_path == "test_jobs.sqlite3"


def test_load_config_missing_token_raises(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_ID", "42")
    monkeypatch.setenv("ADMIN_USERNAME", "admin_user")

    with pytest.raises(KeyError):
        load_config()
