"""The build moment inside a reference: a date that holds on the build day and never again."""
import re
from datetime import datetime, timedelta

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _patterns(day: datetime) -> list[str]:
    """How tools print `day` -- only forms that name a full date or carry a clock (ls -l, date)."""
    mon = _MONTHS[day.month - 1]                                   # C locale, as in the console
    return [
        rf"\b{day:%Y-%m-%d}\b",                                    # ISO: logs, names, stat
        rf"\b{day:%Y/%m/%d}\b",
        rf"\b{day:%d\.%m\.%Y}\b",                                  # dd.mm.yyyy
        rf"\b{mon} +{day.day} +\d{{1,2}}:\d\d\b",                  # ls -l, date: «Oct 23 01:05»
    ]


def build_stamp(text: str, now: datetime) -> str | None:
    """
    Find the first line of `text` that names the day of `now`: a reference that matches only then.

    The day either side counts too -- the build's clock and the reference's timezone may disagree.
    """
    days = (now - timedelta(days=1), now, now + timedelta(days=1))
    found = re.compile("|".join(p for d in days for p in _patterns(d)))
    return next((line for line in text.splitlines() if found.search(line)), None)
