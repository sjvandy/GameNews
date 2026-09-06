from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

DEFAULT_MEDIA_DURATION = timedelta(minutes=60)
DEFAULT_INGAME_DURATION = timedelta(hours=48)

# A narrow pre-filter for date-shaped substrings, checked before handing
# candidates to dateutil's fuzzy parser - this guards against dateutil
# false-positiving on unrelated numbers in a title (e.g. "Splatoon 3" or a
# view count) rather than a genuine date.
#
# The day group uses \d{1,2}(?!\d) (a day, not immediately followed by
# another digit) so a bare "Month Year" mention - e.g. "...Live | September
# 2026" - can't be misread as day=20 with "26" left dangling. Without that
# guard, dateutil fills the *missing* day from today's date, which can
# produce a bogus "today at midnight" candidate that wins the earliest-date
# comparison and gets flagged as already past - silently discarding a
# perfectly good date found elsewhere in the same text (e.g. "9.9.2026").
_DATE_PATTERN = re.compile(
    r"("
    r"\d{1,2}[./]\d{1,2}[./]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?!\d)(?:st|nd|rd|th)?(?:,\s*\d{4})?"
    r"|\d{1,2}(?!\d)(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,\s*\d{4})?"
    r")",
    re.IGNORECASE,
)

# A "7am PT" / "10:30pm ET"-style time-of-day mention. Announcement text for
# Directs/State of Plays reliably states an actual broadcast time this way
# (Nintendo/PlayStation always list Pacific first) - without parsing it, the
# clock time defaults to midnight UTC, which displays as the *previous
# evening* in US timezones and reads as "the wrong date" to anyone west of
# UTC, even though the calendar date itself was extracted correctly.
_TIME_TZ_PATTERN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(pt|pst|pdt|et|est|edt|ct|cst|cdt|mt|mst|mdt)\b",
    re.IGNORECASE,
)

_TZ_ABBREVIATION_TO_IANA = {
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
}


def _extract_time_of_day(text: str) -> tuple[int, int, str] | None:
    """The first "7am PT"-style mention in `text`, as (hour24, minute,
    IANA zone) - or None if no such mention is present."""
    match = _TIME_TZ_PATTERN.search(text or "")
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    return hour, minute, _TZ_ABBREVIATION_TO_IANA[match.group(4).lower()]


@dataclass
class DateRange:
    start: datetime
    end: datetime
    end_was_defaulted: bool = False


def _find_date_candidates(text: str) -> list[str]:
    return [match.group(0) for match in _DATE_PATTERN.finditer(text or "")]


def extract_date_range(
    text: str,
    *,
    default_duration: timedelta,
    reference: datetime | None = None,
) -> DateRange | None:
    """Extract a start (and optional end) datetime from free text.

    Returns None when no start date can be confidently parsed, OR when the
    only date found has already passed - a title can easily contain a real
    past date (an older video sitting in a recently-fetched RSS window, an
    anniversary reference, etc.), and Discord itself rejects creating a
    scheduled event with a start time in the past. Both cases are the same
    "not usable" outcome from the caller's perspective (SRS FR-4/TC-4): skip
    and log, never guess or attempt a doomed API call. A missing *end* is
    not a rejection case: it falls back to `default_duration` (proposed
    60 min for media events, 48h for in-game events).
    """
    now = reference or datetime.now(timezone.utc)
    # Zero out the time-of-day for dateutil's `default`: it borrows any field
    # a candidate string doesn't specify (usually just the year) from
    # `default`, including the clock time - without this, a date-only title
    # like "9.9.2026" would silently inherit the current wall-clock instant,
    # making extraction non-deterministic across runs.
    zeroed_now = now.replace(hour=0, minute=0, second=0, microsecond=0)
    candidates = _find_date_candidates(text)
    if not candidates:
        return None

    parsed: list[datetime] = []
    for candidate in candidates:
        try:
            dt = dateutil_parser.parse(candidate, default=zeroed_now, fuzzy=False)
        except (ValueError, OverflowError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        parsed.append(dt)

    if not parsed:
        return None

    start = min(parsed)
    remaining = [d for d in parsed if d != start]

    # Refine the calendar date's default midnight-UTC clock time to the
    # actual stated broadcast time, if one is present - computed against
    # the *unrefined* start above, since this only corrects the time-of-day,
    # never which candidate is earliest.
    time_of_day = _extract_time_of_day(text)
    if time_of_day is not None:
        hour, minute, iana_zone = time_of_day
        local_start = datetime(start.year, start.month, start.day, hour, minute, tzinfo=ZoneInfo(iana_zone))
        start = local_start.astimezone(timezone.utc)

    if start < now:
        return None

    if remaining:
        end = max(remaining)
        if end <= start:
            end = start + default_duration
        return DateRange(start=start, end=end, end_was_defaulted=False)

    return DateRange(start=start, end=start + default_duration, end_was_defaulted=True)
