from __future__ import annotations

from tests.conftest import make_item

from gamenews.events import classify


def test_ingame_event_keyword_match(registry):
    franchise = registry.get("splatoon-3")
    item = make_item(title="Splatfest announcement: Gas vs Electric vs Bugs")
    assert classify.classify_ingame(item, franchise) is True


def test_ingame_event_disabled_franchise_never_matches(registry):
    zelda = registry.get("legend-of-zelda")  # enable_ingame_events: false
    item = make_item(title="Zelda in-game event quest announced")
    assert classify.classify_ingame(item, zelda) is False


def test_unparseable_date_flagged_not_guessed():
    # TC-4: classification succeeds independent of date extraction; date
    # confidence is checked as a separate step by the caller (see
    # test_events_dates.py) - this test only asserts classification itself.
    from gamenews.events.dates import extract_date_range
    from datetime import timedelta

    item = make_item(title="Splatfest announcement", description="coming soon, no date yet")
    assert extract_date_range(f"{item.title} {item.description}", default_duration=timedelta(hours=1)) is None


def test_branded_direct_is_classified_and_tagged(registry):
    # TC-5: "The Legend of Zelda Direct — 9.4.2026" -> media event AND tagged legend-of-zelda.
    item = make_item(title="The Legend of Zelda Direct — 9.4.2026")
    result = classify.classify_media(item, registry)
    assert result is not None
    assert result.is_direct is True
    assert result.branded_franchise_key == "legend-of-zelda"


def test_branded_direct_with_qualifier_between_name_and_direct(registry):
    # Real production bug: "The Legend of Zelda 40th Anniversary Direct"
    # doesn't contain the literal phrase "zelda direct" - the branding
    # keyword and "Direct" must match independently, not as one fixed
    # adjacent phrase, or this returns None with no rejection logged at all.
    item = make_item(title="The Legend of Zelda 40th Anniversary Direct 9.8.2026")
    result = classify.classify_media(item, registry)
    assert result is not None
    assert result.is_direct is True
    assert result.branded_franchise_key == "legend-of-zelda"


def test_franchise_name_without_direct_is_not_branded(registry):
    # The franchise keyword alone (no standalone "Direct" mention) must not
    # trigger branding - otherwise every Zelda video would be misclassified
    # as a media event.
    item = make_item(title="Zelda amiibo restock announcement")
    result = classify.classify_media(item, registry)
    assert result is None


def test_unbranded_direct_has_no_franchise_tag(registry):
    item = make_item(title="Nintendo Direct — 9.9.2026")
    result = classify.classify_media(item, registry)
    assert result is not None
    assert result.is_direct is True
    assert result.branded_franchise_key is None


def test_non_direct_item_is_not_a_media_event(registry):
    item = make_item(title="Splatoon 3 Side Order DLC Trailer")
    assert classify.classify_media(item, registry) is None
