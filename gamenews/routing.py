from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from gamenews.franchises import FranchiseRegistry, FranchiseSource
from gamenews.sources import ContentItem, instagram, nintendo_news, youtube

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchTarget:
    type: str
    key: str  # channel_id / username / "default" (news is a singleton fetch)


def _target_for(source: FranchiseSource) -> FetchTarget | None:
    """Map a config-facing FranchiseSource to an internal fetch target.

    FetchTarget.type intentionally matches ContentItem.source's vocabulary
    ("nintendo_news", not the config's "news") so callers can match a fetched
    item back to the target that would have produced it - see
    tools/replay.py's _targets_matching, which does exactly that.
    """
    if source.type == "youtube":
        return FetchTarget("youtube", source.channel_id)
    if source.type == "instagram":
        return FetchTarget("instagram", source.username)
    if source.type == "news":
        return FetchTarget("nintendo_news", "default")
    return None  # splatoon3ink is consumed directly by SplatoonScheduleCog, not this pipeline


def collect_fetch_targets(registry: FranchiseRegistry) -> set[FetchTarget]:
    """Every unique fetch target referenced by any franchise or media_events source.

    Multiple consumers (e.g. three franchises all filtering Nintendo's YouTube
    channel by different keywords) collapse to one fetch here.
    """
    targets: set[FetchTarget] = set()
    all_source_lists = [f.sources for f in registry.franchises] + [registry.media_events.sources]
    for sources in all_source_lists:
        for source in sources:
            target = _target_for(source)
            if target is not None:
                targets.add(target)
    return targets


async def fetch_all(targets: set[FetchTarget]) -> dict[FetchTarget, list[ContentItem]]:
    targets_list = list(targets)

    async def _fetch_one(target: FetchTarget) -> list[ContentItem]:
        if target.type == "youtube":
            return await youtube.fetch(target.key)
        if target.type == "instagram":
            return await instagram.fetch(target.key)
        if target.type == "nintendo_news":
            return await nintendo_news.fetch()
        return []

    results = await asyncio.gather(
        *(_fetch_one(t) for t in targets_list), return_exceptions=True
    )

    fetched: dict[FetchTarget, list[ContentItem]] = {}
    for target, result in zip(targets_list, results):
        if isinstance(result, BaseException):
            logger.error("Fetch failed for %s:%s - %s", target.type, target.key, result)
            fetched[target] = []
        else:
            fetched[target] = result
    return fetched


@dataclass
class RoutedItem:
    item: ContentItem
    channel_ids: list[int] = field(default_factory=list)
    matched_franchises: list[str] = field(default_factory=list)


def _matches(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def route_items(
    registry: FranchiseRegistry, fetched: dict[FetchTarget, list[ContentItem]]
) -> list[RoutedItem]:
    """Route each fetched item to every franchise channel whose keywords match
    (FR-2/FR-3), cross-posting on multi-match, with newsroom as the fallback
    for anything that matches no franchise (FR-2, TC-1/TC-2)."""
    routed: list[RoutedItem] = []
    by_unique_id: dict[str, RoutedItem] = {}

    for franchise in registry.franchises:
        for source in franchise.sources:
            target = _target_for(source)
            if target is None or target not in fetched:
                continue
            for item in fetched[target]:
                if source.title_keywords and not _matches(item.title, source.title_keywords):
                    continue

                routed_item = by_unique_id.get(item.unique_id)
                if routed_item is None:
                    routed_item = RoutedItem(item=item)
                    by_unique_id[item.unique_id] = routed_item
                    routed.append(routed_item)

                if franchise.channel_id not in routed_item.channel_ids:
                    routed_item.channel_ids.append(franchise.channel_id)
                if franchise.key not in routed_item.matched_franchises:
                    routed_item.matched_franchises.append(franchise.key)

    for items in fetched.values():
        for item in items:
            if item.unique_id in by_unique_id:
                continue
            routed_item = RoutedItem(
                item=item, channel_ids=[registry.media_events.fallback_channel_id]
            )
            by_unique_id[item.unique_id] = routed_item
            routed.append(routed_item)

    return routed
