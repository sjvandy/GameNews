from __future__ import annotations

from datetime import datetime, timezone

from tests.conftest import make_item

from gamenews.events.builder import build_event_candidate
from gamenews.events.dates import DateRange


def test_valid_ingame_event_payload_shape(registry):
    # TC-3: valid in-game event -> EXTERNAL-ready payload with name, location,
    # start/end, and cover image present.
    franchise = registry.get("splatoon-3")
    item = make_item(
        title="Splatfest announcement: Gas vs Electric vs Bugs",
        image_url="https://example.com/splatfest.jpg",
    )
    date_range = DateRange(
        start=datetime(2026, 9, 10, tzinfo=timezone.utc),
        end=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )

    candidate = build_event_candidate(item, "ingame", date_range, franchise=franchise)

    assert candidate.event_type == "ingame"
    assert candidate.franchise_key == "splatoon-3"
    assert candidate.name
    assert candidate.location
    assert candidate.start_time == date_range.start
    assert candidate.end_time == date_range.end
    assert candidate.cover_image_url == "https://example.com/splatfest.jpg"


def test_name_and_description_are_truncated_for_discord_limits(registry):
    franchise = registry.get("splatoon-3")
    item = make_item(title="x" * 200, description="y" * 2000)
    date_range = DateRange(
        start=datetime(2026, 9, 10, tzinfo=timezone.utc),
        end=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )

    candidate = build_event_candidate(item, "ingame", date_range, franchise=franchise)

    assert len(candidate.name) <= 100
    assert len(candidate.description) <= 1000
    assert len(candidate.location) <= 100
