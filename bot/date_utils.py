from __future__ import annotations

import datetime as dt
import re

# Splits "Текст | ДД.ММ.ГГГГ" (and the /, \ variants) at the first separator.
_OPTION_SEPARATOR_PATTERN = re.compile(r"[|/\\]")

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


class DateParseError(ValueError):
    pass


def parse_date_input(text: str, today: dt.date | None = None) -> dt.date:
    text = text.strip()
    today = today or dt.date.today()
    parts = text.split(".")

    if len(parts) == 2:
        day_str, month_str = parts
        year_str = None
    elif len(parts) == 3:
        day_str, month_str, year_str = parts
        # Validate year_str length before trying to convert
        if len(year_str) not in (2, 4):
            raise DateParseError(
                f"Не удалось разобрать дату: {text!r}. Используйте формат ДД.ММ или ДД.ММ.ГГГГ"
            )
    else:
        raise DateParseError(
            f"Не удалось разобрать дату: {text!r}. Используйте формат ДД.ММ или ДД.ММ.ГГГГ"
        )

    try:
        day = int(day_str)
        month = int(month_str)
        if year_str is None:
            year = today.year
        elif len(year_str) == 2:
            year = 2000 + int(year_str)
        else:  # len(year_str) == 4
            year = int(year_str)
        return dt.date(year, month, day)
    except ValueError as exc:
        raise DateParseError(
            f"Не удалось разобрать дату: {text!r}. Используйте формат ДД.ММ или ДД.ММ.ГГГГ"
        ) from exc


def format_date_ru(d: dt.date) -> str:
    return f"{d.day} {MONTHS_RU[d.month]}"


def parse_option_input(text: str) -> tuple[str, dt.date | None]:
    """Parse a "Текст | ДД.ММ.ГГГГ" line (| / \\ all accepted as separator).

    The date is optional: plain text with no separator is accepted as an
    option with no date (e.g. an open-ended "во что поиграть" option that
    doesn't tie to a specific day). If a separator IS present, whatever
    follows it must be a valid date -- at that point the admin has clearly
    signalled intent to attach one.

    Shared by /newpoll's option entry and /editpoll's "add option" flow so
    both accept the exact same format and raise the exact same error.
    """
    if not text or not text.strip():
        raise DateParseError("Нужно указать текст варианта.")

    match = _OPTION_SEPARATOR_PATTERN.search(text)
    if not match:
        return text.strip(), None

    option_text = text[: match.start()].strip()
    date_part = text[match.end():].strip()
    if not option_text:
        raise DateParseError("Нужно указать текст варианта.")

    return option_text, parse_date_input(date_part)
