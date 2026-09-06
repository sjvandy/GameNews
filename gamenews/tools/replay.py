"""FR-8: dry-run/replay tool.

    python -m gamenews.tools.replay <youtube-url-or-video-id>

Runs a single content item through the exact same routing -> classification ->
event-field-generation code the live bot uses, and prints the result, without
ever importing gamenews.events.lifecycle or calling any Discord API. This is
what keeps the tool honest as a stand-in for the live pipeline (SRS FR-8) and
is also what tests/test_replay_regression.py exercises against committed
fixtures.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime

from gamenews import config
from gamenews.events import classify
from gamenews.events import dates as event_dates
from gamenews.events.builder import EventCandidate, build_event_candidate
from gamenews.franchises import FranchiseRegistry, load_franchises
from gamenews.routing import route_items
from gamenews.sources import ContentItem, youtube

_VIDEO_ID_PATTERN = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")


@dataclass
class ReplayResult:
    unique_id: str
    title: str
    routed_channel_ids: list[int]
    matched_franchises: list[str]
    ingame_event: EventCandidate | None
    media_event: EventCandidate | None
    rejection_reasons: list[str]


def _extract_video_id(url_or_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    match = _VIDEO_ID_PATTERN.search(url_or_id)
    if not match:
        raise ValueError(f"Could not extract a YouTube video ID from '{url_or_id}'")
    return match.group(1)


def run_replay_from_item(
    item: ContentItem, registry: FranchiseRegistry, *, reference: datetime | None = None
) -> ReplayResult:
    """The core, network-free replay logic - shared by the CLI and the
    fixture regression suite (SRS 9.2).

    `reference` pins "now" for date-extraction's past/future check (see
    events/dates.py). The live CLI leaves it as None (real wall-clock time);
    the regression suite pins a fixed value so committed fixtures - which
    embed real calendar dates - never silently start failing years later
    just because time passed them by.
    """
    # A single-item "fetch result" lets us reuse route_items() exactly as the
    # live poller does, rather than reimplementing keyword matching here.
    # An item may legitimately match more than one target only when its exact
    # channel/account is unknown (see _targets_matching); route_items()
    # dedups on unique_id regardless, so union all matches into one fetch.
    targets = list(_targets_matching(item, registry))
    fetched = {target: [item] for target in targets} if targets else {}
    routed = route_items(registry, fetched) if fetched else []
    routed_item = routed[0] if routed else None

    routed_channel_ids = routed_item.channel_ids if routed_item else [
        registry.media_events.fallback_channel_id
    ]
    matched_franchises = routed_item.matched_franchises if routed_item else []

    rejection_reasons: list[str] = []
    ingame_event: EventCandidate | None = None
    for franchise_key in matched_franchises:
        franchise = registry.get(franchise_key)
        if franchise is None or not classify.classify_ingame(item, franchise):
            continue
        date_range = event_dates.extract_date_range(
            f"{item.title} {item.description}",
            default_duration=event_dates.DEFAULT_INGAME_DURATION,
            reference=reference,
        )
        if date_range is None:
            rejection_reasons.append(
                f"in-game event matched for '{franchise_key}' but no parseable (future) date found"
            )
            continue
        ingame_event = build_event_candidate(item, "ingame", date_range, franchise=franchise)
        break

    media_event: EventCandidate | None = None
    media_classification = classify.classify_media(item, registry)
    if media_classification and media_classification.is_direct:
        date_range = event_dates.extract_date_range(
            f"{item.title} {item.description}",
            default_duration=event_dates.DEFAULT_MEDIA_DURATION,
            reference=reference,
        )
        if date_range is None:
            rejection_reasons.append("media event matched but no parseable (future) date found")
        else:
            branded_franchise = registry.get(media_classification.branded_franchise_key)
            media_event = build_event_candidate(
                item,
                "media",
                date_range,
                franchise=branded_franchise,
                branded_franchise_key=media_classification.branded_franchise_key,
            )

    return ReplayResult(
        unique_id=item.unique_id,
        title=item.title,
        routed_channel_ids=routed_channel_ids,
        matched_franchises=matched_franchises,
        ingame_event=ingame_event,
        media_event=media_event,
        rejection_reasons=rejection_reasons,
    )


def _targets_matching(item: ContentItem, registry: FranchiseRegistry):
    """Yield the FetchTarget(s) that would have produced this item, so
    route_items() can be reused unmodified for a single ad-hoc item.

    Matching purely on item.source (e.g. "youtube") isn't enough once more
    than one franchise references a "youtube" source - each references a
    *different* channel_id, and only the item's own channel disambiguates
    which one actually would have fetched it. That channel/account is read
    from ContentItem.extra (populated by sources/youtube.py::fetch /
    fetch_single, or sources/instagram.py::fetch).

    If it's genuinely unknown (e.g. a transient failure extracting it),
    nothing is yielded rather than guessing across every same-type target:
    guessing is actively unsafe here, since an unfiltered franchise source
    (empty title_keywords, e.g. Monster Hunter's "ingest everything") would
    then wrongly claim a totally unrelated item.
    """
    from gamenews.routing import _target_for  # local import: internal helper, replay-only use

    if item.source == "youtube":
        item_key = item.extra.get("channel_id")
    elif item.source == "instagram":
        item_key = item.extra.get("username")
    else:
        item_key = "default"

    if item_key is None:
        return

    def source_key(source) -> str | None:
        if source.type == "youtube":
            return source.channel_id
        if source.type == "instagram":
            return source.username
        if source.type == "news":
            return "default"
        return None

    seen: set = set()
    all_sources = [s for franchise in registry.franchises for s in franchise.sources]
    all_sources += registry.media_events.sources

    for source in all_sources:
        target = _target_for(source)
        if target is None or target.type != item.source:
            continue
        if source_key(source) != item_key:
            continue
        if target not in seen:
            seen.add(target)
            yield target


async def run_replay(url_or_id: str, registry: FranchiseRegistry) -> ReplayResult:
    video_id = _extract_video_id(url_or_id)
    item = await youtube.fetch_single(video_id)
    if item is None:
        raise RuntimeError(f"Could not fetch video {video_id}")
    return run_replay_from_item(item, registry)


def _to_jsonable(result: ReplayResult) -> dict:
    def _convert(obj):
        if dataclasses.is_dataclass(obj):
            return _convert(dataclasses.asdict(obj))
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(v) for v in obj]
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

    return _convert(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="GameNews FR-8 dry-run replay tool")
    parser.add_argument("url", help="YouTube video URL or video ID")
    parser.add_argument(
        "--franchises",
        default=config.FRANCHISES_CONFIG_PATH,
        help="Path to franchises.yaml (default: %(default)s)",
    )
    args = parser.parse_args()

    registry = load_franchises(args.franchises)
    result = asyncio.run(run_replay(args.url, registry))
    json.dump(_to_jsonable(result), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
