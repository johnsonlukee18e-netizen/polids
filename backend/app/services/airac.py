"""Cykl AIRAC: 28-dniowe cykle liczone od 2 stycznia 2020 (cykl 2001)."""

from datetime import date, timedelta

EPOCH = date(2020, 1, 2)
CYCLE = timedelta(days=28)


def current_airac(today: date | None = None) -> dict:
    today = today or date.today()
    n = (today - EPOCH) // CYCLE
    start = EPOCH + n * CYCLE
    # numer w roku: ile cykli zaczęło się w tym samym roku do `start` włącznie
    first_in_year = start
    while (first_in_year - CYCLE).year == start.year:
        first_in_year -= CYCLE
    num = (start - first_in_year) // CYCLE + 1
    return {
        "ident": f"{start.year % 100:02d}{num:02d}",
        "effective": start.isoformat(),
        "next": (start + CYCLE).isoformat(),
    }
