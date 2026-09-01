import datetime as dt

from bot.formatting import (
    build_message_link,
    checkme_empty_text,
    checkme_header,
    cleared_service_messages_text,
    format_option_line,
    mygames_empty_text,
    mygames_header,
    option_date_changed_notification,
    option_deleted_notification,
    option_text_changed_notification,
    poll_message_text,
    record_line,
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


def test_format_option_line_without_date():
    line = format_option_line(1, "Во что поиграть", None, 2)
    assert line == "1. Во что поиграть — 2 🗳"


def test_poll_message_text_joins_lines():
    text = poll_message_text("Игра в апреле", ["1. 24.07 — 2 🗳", "2. 25.07 — 0 🗳"])
    assert text == "📅 Игра в апреле\n\n1. 24.07 — 2 🗳\n2. 25.07 — 0 🗳"


def test_threshold_reached_text():
    text = threshold_reached_text("@admin", "24.07", dt.date(2026, 7, 24))
    assert text == '@admin, за вариант "24.07 24 июля" достаточно голосов для брони!'


def test_threshold_dropped_text():
    text = threshold_dropped_text("24.07", dt.date(2026, 7, 24))
    assert text == (
        'За вариант "24.07 24 июля" снова меньше 4х человек. Проголосуйте, а то игра отменится!'
    )


def test_threshold_reached_text_without_date():
    text = threshold_reached_text("@admin", "Во что поиграть", None)
    assert text == '@admin, за вариант "Во что поиграть" достаточно голосов для брони!'


def test_threshold_dropped_text_without_date():
    text = threshold_dropped_text("Во что поиграть", None)
    assert text == (
        'За вариант "Во что поиграть" снова меньше 4х человек. Проголосуйте, а то игра отменится!'
    )


def test_option_deleted_notification_lists_voters():
    text = option_deleted_notification("24.07", dt.date(2026, 7, 24), ["@alice", "Bob"])
    assert text == (
        "@alice, Bob, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24 июля (24.07)» удалён."
    )


def test_option_deleted_notification_without_voters():
    text = option_deleted_notification("24.07", dt.date(2026, 7, 24), [])
    assert text == (
        "вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «24 июля (24.07)» удалён."
    )


def test_option_deleted_notification_without_date():
    text = option_deleted_notification("Во что поиграть", None, ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: вариант «Во что поиграть» удалён."
    )


def test_option_text_changed_notification():
    text = option_text_changed_notification(
        "24.07", "24.07 (уточнено время)", dt.date(2026, 7, 24), ["@alice"]
    )
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: «24 июля (24.07)» → «24 июля (24.07 (уточнено время))»."
    )


def test_option_text_changed_notification_without_date():
    text = option_text_changed_notification("24.07", "24.07 (уточнено время)", None, ["@alice"])
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


def test_option_date_changed_notification_from_no_date():
    text = option_date_changed_notification("Игра", None, dt.date(2026, 7, 26), ["@alice"])
    assert text == (
        "@alice, вы проголосовали за вариант, но он изменился! "
        "В опрос внесены изменения: у «Игра» появилась дата: 26 июля."
    )


def test_reminder_text_lists_participants():
    text = reminder_text(dt.date(2026, 7, 25), ["@alice", "Bob"])
    assert text == (
        "Напоминаю, что завтра, 25 июля, состоится игра! "
        "Пожалуйста, подтвердите участие реакцией на это сообщение:\n@alice\nBob"
    )


def test_build_message_link_with_username():
    assert build_message_link(-1001234567890, 42, "somechat") == "https://t.me/somechat/42"


def test_build_message_link_supergroup_without_username():
    assert build_message_link(-1001234567890, 42, None) == "https://t.me/c/1234567890/42"


def test_build_message_link_basic_group_without_username_returns_none():
    assert build_message_link(-123456789, 42, None) is None


def test_record_line_escapes_and_links():
    line = record_line(1, "Настолки <3", dt.date(2026, 8, 22), "Компания А & Ко", 3, "https://t.me/c/1/2")
    assert line == (
        '1. <a href="https://t.me/c/1/2">22 августа, Настолки &lt;3</a> '
        "(Компания А &amp; Ко, 3 игрока)"
    )


def test_record_line_pluralizes_players_count():
    cases = {1: "1 игрок", 2: "2 игрока", 5: "5 игроков", 11: "11 игроков", 21: "21 игрок"}
    for count, expected in cases.items():
        line = record_line(1, "Игра", dt.date(2026, 8, 22), "Чат", count, "https://t.me/c/1/2")
        assert line.endswith(f"(Чат, {expected})"), f"count={count}: {line!r}"


def test_checkme_header_escapes():
    assert checkme_header("Alice & Bob") == "Alice &amp; Bob, вы записаны:"


def test_checkme_empty_text_escapes():
    assert checkme_empty_text("Alice & Bob") == "Alice &amp; Bob, у вас нет записей на игры."


def test_mygames_header_escapes():
    assert mygames_header("Alice & Bob") == "Alice &amp; Bob, вы играли:"


def test_mygames_empty_text_escapes():
    assert mygames_empty_text("Alice & Bob") == "Alice &amp; Bob, у вас нет прошедших игр."


def test_cleared_service_messages_text_with_nothing_deleted():
    assert cleared_service_messages_text(0) == "Нечего удалять."


def test_cleared_service_messages_text_pluralizes_count():
    cases = {1: "Удалено 1 сообщение.", 2: "Удалено 2 сообщения.", 5: "Удалено 5 сообщений.", 11: "Удалено 11 сообщений.", 21: "Удалено 21 сообщение."}
    for count, expected in cases.items():
        assert cleared_service_messages_text(count) == expected, f"count={count}"
