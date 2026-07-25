import datetime as dt

import pytest

from bot.date_utils import DateParseError, format_date_ru, parse_date_input, parse_option_input


def test_parse_full_date():
    assert parse_date_input("24.07.2026") == dt.date(2026, 7, 24)


def test_parse_two_digit_year():
    assert parse_date_input("24.07.26") == dt.date(2026, 7, 24)


def test_parse_date_without_year_uses_today_year():
    result = parse_date_input("24.07", today=dt.date(2026, 1, 1))
    assert result == dt.date(2026, 7, 24)


def test_parse_invalid_format_raises():
    with pytest.raises(DateParseError):
        parse_date_input("not-a-date")


def test_parse_invalid_calendar_date_raises():
    with pytest.raises(DateParseError):
        parse_date_input("32.13.2026")


def test_parse_invalid_year_length_single_digit_raises():
    with pytest.raises(DateParseError):
        parse_date_input("24.07.6")


def test_parse_invalid_year_length_three_digit_raises():
    with pytest.raises(DateParseError):
        parse_date_input("24.07.026")


def test_parse_non_numeric_year_raises():
    with pytest.raises(DateParseError):
        parse_date_input("24.07.ab")


def test_parse_non_numeric_four_digit_year_raises():
    with pytest.raises(DateParseError):
        parse_date_input("24.07.abcd")


def test_format_date_ru():
    assert format_date_ru(dt.date(2026, 7, 24)) == "24 июля"


def test_parse_option_input_pipe_separator():
    text, date = parse_option_input("24.07 | 24.07.2026")
    assert text == "24.07"
    assert date == dt.date(2026, 7, 24)


def test_parse_option_input_slash_separator():
    text, date = parse_option_input("24.07 / 24.07.2026")
    assert text == "24.07"
    assert date == dt.date(2026, 7, 24)


def test_parse_option_input_backslash_separator():
    text, date = parse_option_input("24.07 \\ 24.07.2026")
    assert text == "24.07"
    assert date == dt.date(2026, 7, 24)


def test_parse_option_input_no_separator_raises():
    with pytest.raises(DateParseError):
        parse_option_input("24.07 24.07.2026")


def test_parse_option_input_invalid_date_raises():
    with pytest.raises(DateParseError):
        parse_option_input("24.07 | not-a-date")
