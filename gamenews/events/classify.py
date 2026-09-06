from __future__ import annotations

import re
from dataclasses import dataclass

from gamenews.franchises import Franchise, FranchiseRegistry
from gamenews.sources import ContentItem

# A standalone "Direct" mention, used to confirm a franchise-branding keyword
# match is actually about a Direct-style broadcast, not just any mention of
# the franchise's name.
_DIRECT_WORD_PATTERN = re.compile(r"\bdirect\b", re.IGNORECASE)


@dataclass
class MediaClassification:
    is_direct: bool
    branded_franchise_key: str | None


def _matches_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _haystack(item: ContentItem) -> str:
    return f"{item.title} {item.description}"


def classify_ingame(item: ContentItem, franchise: Franchise) -> bool:
    """FR-4: does this item announce a limited-time in-game event for `franchise`?"""
    if not franchise.enable_ingame_events or not franchise.event_keywords:
        return False
    return _matches_any(_haystack(item), franchise.event_keywords)


def classify_media(item: ContentItem, registry: FranchiseRegistry) -> MediaClassification | None:
    """FR-5: is this item a Direct/State-of-Play, and if so, is it franchise-branded (TC-5)?

    A branding keyword (e.g. "zelda") plus the standalone word "Direct"
    anywhere in the text marks a franchise-branded Direct - deliberately not
    requiring them adjacent as one fixed phrase. A real title like "The
    Legend of Zelda 40th Anniversary Direct" doesn't contain "zelda direct"
    verbatim (the qualifier sits between them), so a fixed-phrase match
    would silently miss exactly the branded case FR-5/TC-5 cares about, with
    no rejection logged at all since classification itself would return
    None. Deliberately date-agnostic - classification must succeed
    independent of whether a start/end date is parseable.
    """
    haystack = _haystack(item)
    has_direct_word = bool(_DIRECT_WORD_PATTERN.search(haystack))

    branded_key = None
    for key, branding_keywords in registry.media_events.franchise_branding_keywords.items():
        if has_direct_word and _matches_any(haystack, branding_keywords):
            branded_key = key
            break

    is_direct = branded_key is not None or _matches_any(haystack, registry.media_events.keywords())
    if not is_direct:
        return None

    return MediaClassification(is_direct=True, branded_franchise_key=branded_key)
