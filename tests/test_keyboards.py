from bot.keyboards import build_poll_keyboard


def test_build_poll_keyboard_creates_one_button_per_option():
    markup = build_poll_keyboard([(1, "24.07", 2), (2, "25.07", 0)])

    rows = markup.inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].text == "24.07 (2)"
    assert rows[0][0].callback_data == "vote:1"
    assert rows[1][0].text == "25.07 (0)"
    assert rows[1][0].callback_data == "vote:2"
