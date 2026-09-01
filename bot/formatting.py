from __future__ import annotations

import datetime as dt
import html

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


def build_message_link(chat_id: int, message_id: int, username: str | None) -> str | None:
    if username:
        return f"https://t.me/{username}/{message_id}"
    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        return f"https://t.me/c/{chat_id_str[4:]}/{message_id}"
    return None


def _pluralize_players(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "игрок"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "игрока"
    return "игроков"


def record_line(
    index: int, option_text: str, option_date: dt.date, chat_title: str, vote_count: int, link: str
) -> str:
    label = f"{format_date_ru(option_date)}, {html.escape(option_text)}"
    players = f"{vote_count} {_pluralize_players(vote_count)}"
    return (
        f'{index}. <a href="{html.escape(link)}">{label}</a> '
        f"({html.escape(chat_title)}, {players})"
    )


def checkme_header(mention: str) -> str:
    return f"{html.escape(mention)}, вы записаны:"


def checkme_empty_text(mention: str) -> str:
    return f"{html.escape(mention)}, у вас нет записей на игры."


def mygames_header(mention: str) -> str:
    return f"{html.escape(mention)}, вы играли:"


def mygames_empty_text(mention: str) -> str:
    return f"{html.escape(mention)}, у вас нет прошедших игр."


def _pluralize_messages(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "сообщение"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "сообщения"
    return "сообщений"


def cleared_service_messages_text(deleted_count: int) -> str:
    if deleted_count == 0:
        return "Нечего удалять."
    return f"Удалено {deleted_count} {_pluralize_messages(deleted_count)}."
