from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.conftest import make_item

from gamenews.cogs.content_poll import is_stale
from gamenews.routing import FetchTarget, route_items


NINTENDO_YT = FetchTarget("youtube", "UCGIY_O-8vW4rfX98KlMkvRg")


def test_franchise_keyword_match_routes_to_franchise_channel(registry):
    # TC-1: "Splatoon 3 Side Order DLC Trailer" routes to splatoon-3.
    item = make_item(title="Splatoon 3 Side Order DLC Trailer")
    routed = route_items(registry, {NINTENDO_YT: [item]})

    assert len(routed) == 1
    splatoon = registry.get("splatoon-3")
    assert routed[0].channel_ids == [splatoon.channel_id]
    assert routed[0].matched_franchises == ["splatoon-3"]


def test_no_keyword_match_falls_back_to_newsroom(registry):
    # TC-2: no franchise keyword match falls back to newsroom.
    item = make_item(title="Super Mario Kart World amiibo unboxing")
    routed = route_items(registry, {NINTENDO_YT: [item]})

    assert len(routed) == 1
    assert routed[0].channel_ids == [registry.media_events.fallback_channel_id]
    assert routed[0].matched_franchises == []


def test_multi_franchise_match_cross_posts_to_both_channels(registry):
    item = make_item(title="Splatoon 3 x Zelda crossover amiibo announcement")
    routed = route_items(registry, {NINTENDO_YT: [item]})

    assert len(routed) == 1
    splatoon = registry.get("splatoon-3")
    zelda = registry.get("legend-of-zelda")
    assert set(routed[0].channel_ids) == {splatoon.channel_id, zelda.channel_id}
    assert set(routed[0].matched_franchises) == {"splatoon-3", "legend-of-zelda"}


def test_unfiltered_source_ingests_everything(registry):
    mh_target = FetchTarget("youtube", "UCVS0xBpOtXBAl12rdG67-OQ")
    item = make_item(title="Monster Hunter Rise amiibo unboxing")
    routed = route_items(registry, {mh_target: [item]})

    mh = registry.get("monster-hunter")
    assert routed[0].channel_ids == [mh.channel_id]


def test_is_stale_rejects_content_older_than_cutoff():
    # Real production case: "Capcom Spotlight - June 2026" was still sitting
    # in a channel's last-15-videos RSS window months later and got posted
    # as if brand new. Age-gating must catch this even on first sight.
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    old_item = make_item(published_at=now - timedelta(days=73))
    assert is_stale(old_item, max_age_days=30, now=now) is True


def test_is_stale_accepts_recent_content():
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    recent_item = make_item(published_at=now - timedelta(days=2))
    assert is_stale(recent_item, max_age_days=30, now=now) is False


def test_is_stale_never_suppresses_unknown_age():
    from gamenews.sources import ContentItem

    item = ContentItem(
        source="nintendo_news",
        unique_id="nintendo:unknown-date",
        title="Untitled",
        url="https://www.nintendo.com/us/whatsnew/example",
        description="",
        image_url="",
        published_at=None,
    )
    assert is_stale(item, max_age_days=30) is False
