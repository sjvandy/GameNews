from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gamenews.events.dates import extract_date_range


def test_no_date_returns_none():
    # TC-4: unparseable dates must return None, never a guessed value.
    assert extract_date_range("Splatoon 3 Side Order DLC Trailer", default_duration=timedelta(hours=1)) is None


def test_past_date_returns_none():
    # A real production bug: an old State of Play video sitting in the RSS
    # feed's recent window had a real, already-passed date in its title.
    # Discord rejects "Cannot schedule event in the past" - extraction must
    # treat a past date the same as no date at all (skip and log), rather
    # than attempting a doomed event-creation call.
    reference = datetime(2026, 9, 6, tzinfo=timezone.utc)
    result = extract_date_range(
        "State of Play | September 12, 2025",
        default_duration=timedelta(hours=1),
        reference=reference,
    )
    assert result is None


def test_single_date_defaults_end_time():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = extract_date_range(
        "The Legend of Zelda Direct — 9.4.2026",
        default_duration=timedelta(minutes=60),
        reference=reference,
    )
    assert result is not None
    assert result.start.month == 9 and result.start.day == 4 and result.start.year == 2026
    assert result.end == result.start + timedelta(minutes=60)
    assert result.end_was_defaulted is True


def test_bare_month_year_mention_does_not_poison_a_real_date():
    # Real production bug: a description containing an unrelated bare
    # "Month Year" mention (no day) was mis-parsed as day=20 with digits
    # left over, borrowing *today's* day-of-month for the missing day and
    # producing a bogus "today" candidate that beat the real date "9.9.2026"
    # in the earliest-date comparison, incorrectly rejecting the whole item
    # as past-dated.
    reference = datetime(2026, 9, 6, tzinfo=timezone.utc)
    text = (
        "Nintendo Direct 9.9.2026 Join us on September 9 at 7am PT for Nintendo "
        "Direct 9.9.2026. After Nintendo Direct 9.9.2026, tune in to Nintendo "
        "Treehouse: Live | September 2026 to watch gameplay."
    )
    result = extract_date_range(text, default_duration=timedelta(minutes=60), reference=reference)
    assert result is not None
    # 7am PT on Sept 9 = 14:00 UTC (PDT is UTC-7 in September) - confirms
    # both fixes at once: the right calendar date, and now the right time.
    assert result.start == datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


def test_broadcast_time_with_timezone_refines_default_midnight():
    # Real production bug: a title/description with only a calendar date
    # ("9.8.2026") defaulted to midnight UTC, which displays as the previous
    # evening in US timezones ("Sep 7, 5:00 PM" for a Sept 8 event) - reads
    # as "the wrong date" even though the calendar date was right. The
    # actual stated broadcast time ("7am PT / 10am ET") must be used instead.
    reference = datetime(2026, 9, 1, tzinfo=timezone.utc)
    text = (
        "The Legend of Zelda 40th Anniversary Direct 9.8.2026 "
        "Join us on September 8 at 7am PT / 10am ET for The Legend of Zelda "
        "40th Anniversary Direct."
    )
    result = extract_date_range(text, default_duration=timedelta(minutes=60), reference=reference)
    assert result is not None
    assert result.start == datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)  # 7am PDT
    assert result.end == datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def test_eastern_time_broadcast_time_is_supported():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    text = "Capcom Spotlight arrives on June 25 at 2pm ET, 2026"
    result = extract_date_range(text, default_duration=timedelta(minutes=60), reference=reference)
    assert result is not None
    assert result.start == datetime(2026, 6, 25, 18, 0, tzinfo=timezone.utc)  # 2pm EDT


def test_no_time_mention_still_defaults_to_midnight():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = extract_date_range(
        "Nintendo Direct 9.9.2026", default_duration=timedelta(minutes=60), reference=reference
    )
    assert result is not None
    assert result.start == datetime(2026, 9, 9, tzinfo=timezone.utc)


def test_start_and_end_date_both_parsed():
    reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = extract_date_range(
        "Big Run event runs from September 4 to September 8, 2026",
        default_duration=timedelta(hours=1),
        reference=reference,
    )
    assert result is not None
    assert result.start.day == 4
    assert result.end.day == 8
    assert result.end_was_defaulted is False
