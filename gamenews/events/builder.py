from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from gamenews.events.dates import DateRange
from gamenews.franchises import Franchise
from gamenews.sources import ContentItem


@dataclass
class EventCandidate:
    """A fully-formed, Discord-ready event payload - pure data, no network I/O.

    `cover_image_url` stays a URL string (not bytes) so this stays reusable by
    both the live pipeline and the FR-8 replay tool; only lifecycle.py, at
    actual creation time, downloads the bytes.
    """

    event_type: str  # "ingame" | "media"
    franchise_key: str | None
    branded_franchise_key: str | None
    source_unique_id: str
    name: str
    description: str
    start_time: datetime
    end_time: datetime
    location: str
    cover_image_url: str | None


def build_event_candidate(
    item: ContentItem,
    event_type: str,
    date_range: DateRange,
    *,
    franchise: Franchise | None = None,
    branded_franchise_key: str | None = None,
    location_override: str | None = None,
) -> EventCandidate:
    # Discord's EXTERNAL event location field is meant for exactly this - a
    # link/address for the event - so it always points back to the source
    # content (the YouTube video, news article, etc.) rather than a static
    # "Franchise — Online" label. This is also what lets a separate content
    # post be skipped when an event is created for the same item (see
    # ContentPollCog.maybe_create_events): the event card itself is the link.
    location = location_override or item.url or "Online"

    return EventCandidate(
        event_type=event_type,
        franchise_key=franchise.key if franchise else None,
        branded_franchise_key=branded_franchise_key,
        source_unique_id=item.unique_id,
        name=item.title[:100],
        description=(item.description or "")[:1000],
        start_time=date_range.start,
        end_time=date_range.end,
        location=location[:100],
        cover_image_url=item.image_url or None,
    )
