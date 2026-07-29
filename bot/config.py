from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    admin_username: str
    timezone: ZoneInfo
    reminder_hour: int
    reminder_minute: int
    db_path: str
    jobs_db_path: str
    threshold_debounce_seconds: int


def _require_env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it in your hosting panel (or .env) before starting the bot."
        ) from None


def _resolve_data_path(path: str, data_dir: str) -> str:
    """Resolve a DB path against DATA_DIR.

    Absolute paths are returned unchanged. Relative paths are placed inside
    DATA_DIR when it is set, so bothost.ru's persistent /app/data volume is
    used even when the panel supplies bare relative filenames. With DATA_DIR
    unset, relative paths are left as-is (local dev / systemd, where the
    working directory already persists).
    """
    if os.path.isabs(path) or not data_dir:
        return path
    return os.path.join(data_dir, path)


def load_config() -> Config:
    bot_token = _require_env("BOT_TOKEN")
    admin_id = int(_require_env("ADMIN_ID"))
    admin_username = _require_env("ADMIN_USERNAME")
    timezone = ZoneInfo(os.environ.get("BOT_TIMEZONE", "Europe/Moscow"))

    reminder_time = os.environ.get("REMINDER_TIME", "19:00")
    hour_str, minute_str = reminder_time.split(":")

    data_dir = os.environ.get("DATA_DIR", "")
    db_path = _resolve_data_path(os.environ.get("DB_PATH", "poll_bot.sqlite3"), data_dir)
    jobs_db_path = _resolve_data_path(os.environ.get("JOBS_DB_PATH", "jobs.sqlite3"), data_dir)
    threshold_debounce_seconds = int(os.environ.get("THRESHOLD_DEBOUNCE_SECONDS", "900"))

    return Config(
        bot_token=bot_token,
        admin_id=admin_id,
        admin_username=admin_username,
        timezone=timezone,
        reminder_hour=int(hour_str),
        reminder_minute=int(minute_str),
        db_path=db_path,
        jobs_db_path=jobs_db_path,
        threshold_debounce_seconds=threshold_debounce_seconds,
    )
