import datetime as dt

from bot.keyboards import build_poll_keyboard


def test_build_poll_keyboard_creates_one_button_per_option():
    markup = build_poll_keyboard(
        [
            (1, "24.07", dt.date(2026, 7, 24), 2),
            (2, "25.07", dt.date(2026, 7, 25), 0),
        ]
    )

    rows = markup.inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].text == "24.07 (24 июля) — 2"
    assert rows[0][0].callback_data == "vote:1"
    assert rows[1][0].text == "25.07 (25 июля) — 0"
    assert rows[1][0].callback_data == "vote:2"
