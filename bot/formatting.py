from __future__ import annotations

import datetime as dt

from bot.date_utils import format_date_ru


def voter_mention(username: str | None, first_name: str) -> str:
    if username:
        return f"@{username}"
    return first_name


def format_option_line(
    index: int,
    option_text: str,
    option_date: dt.date,
    vote_count: int,
    voter_mentions: list[str] | None = None,
) -> str:
    line = f"{index}. {option_text} ({format_date_ru(option_date)}) — {vote_count} 🗳"
    if voter_mentions:
        line += f"\n   {', '.join(voter_mentions)}"
    return line


def poll_message_text(title: str, option_lines: list[str]) -> str:
    body = "\n".join(option_lines)
    return f"📅 {title}\n\n{body}"


def threshold_reached_text(admin_mention: str, option_text: str, option_date: dt.date) -> str:
    return (
        f'{admin_mention}, за вариант "{option_text} {format_date_ru(option_date)}" '
        f"достаточно голосов для брони!"
    )


def threshold_dropped_text(option_text: str, option_date: dt.date) -> str:
    return (
        f'За вариант "{option_text} {format_date_ru(option_date)}" снова меньше 4х человек. '
        f"Проголосуйте, а то игра отменится!"
    )


def option_deleted_notification(option_text: str, voter_mentions: list[str]) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: вариант «{option_text}» удалён."
    )


def option_text_changed_notification(old_text: str, new_text: str, voter_mentions: list[str]) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{old_text}» → «{new_text}»."
    )


def option_date_changed_notification(
    option_text: str, old_date: dt.date, new_date: dt.date, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{option_text}» перенесён с {format_date_ru(old_date)} "
        f"на {format_date_ru(new_date)}."
    )


def reminder_text(option_date: dt.date, participant_mentions: list[str]) -> str:
    participants_block = "\n".join(participant_mentions)
    return (
        f"Напоминаю, что завтра, {format_date_ru(option_date)}, состоится игра! "
        f"Пожалуйста, подтвердите участие реакцией на это сообщение:\n{participants_block}"
    )
