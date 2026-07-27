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
    option_date: dt.date | None,
    vote_count: int,
    voter_mentions: list[str] | None = None,
) -> str:
    date_part = f" ({format_date_ru(option_date)})" if option_date is not None else ""
    line = f"{index}. {option_text}{date_part} — {vote_count} 🗳"
    if voter_mentions:
        line += f"\n   {', '.join(voter_mentions)}"
    return line


def poll_message_text(title: str, option_lines: list[str]) -> str:
    body = "\n".join(option_lines)
    return f"📅 {title}\n\n{body}"


def threshold_reached_text(admin_mention: str, option_text: str, option_date: dt.date | None) -> str:
    label = f"{option_text} {format_date_ru(option_date)}" if option_date is not None else option_text
    return f'{admin_mention}, за вариант "{label}" достаточно голосов для брони!'


def threshold_dropped_text(option_text: str, option_date: dt.date | None) -> str:
    label = f"{option_text} {format_date_ru(option_date)}" if option_date is not None else option_text
    return (
        f'За вариант "{label}" снова меньше 4х человек. '
        f"Проголосуйте, а то игра отменится!"
    )


def _dated_label(option_text: str, option_date: dt.date | None) -> str:
    if option_date is None:
        return option_text
    return f"{format_date_ru(option_date)} ({option_text})"


def option_deleted_notification(
    option_text: str, option_date: dt.date | None, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    label = _dated_label(option_text, option_date)
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: вариант «{label}» удалён."
    )


def option_text_changed_notification(
    old_text: str, new_text: str, option_date: dt.date | None, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    old_label = _dated_label(old_text, option_date)
    new_label = _dated_label(new_text, option_date)
    return (
        f"{prefix}вы проголосовали за вариант, но он изменился! "
        f"В опрос внесены изменения: «{old_label}» → «{new_label}»."
    )


def option_date_changed_notification(
    option_text: str, old_date: dt.date | None, new_date: dt.date, voter_mentions: list[str]
) -> str:
    prefix = f"{', '.join(voter_mentions)}, " if voter_mentions else ""
    if old_date is None:
        change = f"у «{option_text}» появилась дата: {format_date_ru(new_date)}"
    else:
        change = (
            f"«{option_text}» перенесён с {format_date_ru(old_date)} на {format_date_ru(new_date)}"
        )
    return f"{prefix}вы проголосовали за вариант, но он изменился! В опрос внесены изменения: {change}."


def reminder_text(option_date: dt.date, participant_mentions: list[str]) -> str:
    participants_block = "\n".join(participant_mentions)
    return (
        f"Напоминаю, что завтра, {format_date_ru(option_date)}, состоится игра! "
        f"Пожалуйста, подтвердите участие реакцией на это сообщение:\n{participants_block}"
    )
