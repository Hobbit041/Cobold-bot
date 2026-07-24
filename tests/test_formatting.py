import datetime as dt

from bot.formatting import (
    format_option_line,
    option_date_changed_notification,
    option_deleted_notification,
    option_text_changed_notification,
    poll_message_text,
    reminder_text,
    threshold_dropped_text,
    threshold_reached_text,
    voter_mention,
)


def test_voter_mention_with_username():
    assert voter_mention("alice", "Alice") == "@alice"


def test_voter_mention_without_username_falls_back_to_first_name():
    assert voter_mention(None, "Bob") == "Bob"


def test_format_option_line_without_voters():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 2)
    assert line == "1. 24.07 (24 июля) — 2 🗳"


def test_format_option_line_with_voters():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 2, ["@alice", "Bob"])
    assert line == "1. 24.07 (24 июля) — 2 🗳\n   @alice, Bob"


def test_format_option_line_with_empty_voter_list():
    line = format_option_line(1, "24.07", dt.date(2026, 7, 24), 0, [])
    assert line == "1. 24.07 (24 июля) — 0 🗳"


def test_poll_message_text_joins_lines():
    text = poll_message_text("Игра в апреле", ["1. 24.07 — 2 🗳", "2. 25.07 — 0 🗳"])
    assert text == "📅 Игра в апреле\n\n1. 24.07 — 2 🗳\n2. 25.07 — 0 🗳"


def test_threshold_reached_text():
    text = threshold_reached_text("@admin", "24.07", dt.date(2026, 7, 24))
    assert text == '@admin, за вариант "24.07 24 июля" достаточно голосов для брони!'


def test_threshold_dropped_text():
    text = threshold_dropped_text("24.07")
    assert text == "За вариант «24.07» снова меньше 4х человек. Проголосуйте, а то игра отменится!"


def test_option_deleted_notification_lists_voters():
    text = option_deleted_notification("24.07", ["@alice", "Bob"])
    assert text == (
        "@alice, Bob, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24.07» удалён."
    )


def test_option_deleted_notification_without_voters():
    text = option_deleted_notification("24.07", [])
    assert text == "вы проголосовали за вариант, но он изменился! В опрос внесены изменения: вариант «24.07» удалён."


def test_option_text_changed_notification():
    text = option_text_changed_notification("24.07", "24.07 (уточнено время)", ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24.07» → «24.07 (уточнено время)»."
    )


def test_option_date_changed_notification():
    text = option_date_changed_notification("Игра", dt.date(2026, 7, 24), dt.date(2026, 7, 26), ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «Игра» перенесён с 24 июля на 26 июля."
    )


def test_reminder_text_lists_participants():
    text = reminder_text(dt.date(2026, 7, 25), ["@alice", "Bob"])
    assert text == (
        "Напоминаю, что завтра, 25 июля, состоится игра! "
        "Пожалуйста, подтвердите участие реакцией на это сообщение:\n@alice\nBob"
    )
