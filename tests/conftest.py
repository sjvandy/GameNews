from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from gamenews.franchises import FranchiseRegistry, load_franchises
from gamenews.sources import ContentItem

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def load_item_fixture(path: pathlib.Path) -> ContentItem:
    raw = json.loads(path.read_text())
    published_at = raw.get("published_at")
    return ContentItem(
        source=raw["source"],
        unique_id=raw["unique_id"],
        title=raw["title"],
        url=raw["url"],
        description=raw["description"],
        image_url=raw["image_url"],
        published_at=datetime.fromisoformat(published_at) if published_at else None,
        extra=raw.get("extra", {}),
    )


@pytest.fixture
def registry() -> FranchiseRegistry:
    return load_franchises(str(FIXTURES_DIR / "franchises" / "valid.yaml"))


def make_item(
    *,
    source: str = "youtube",
    unique_id: str = "youtube:abc123",
    title: str = "Untitled",
    description: str = "",
    url: str = "https://www.youtube.com/watch?v=abc123",
    image_url: str = "",
    published_at: datetime | None = None,
) -> ContentItem:
    return ContentItem(
        source=source,
        unique_id=unique_id,
        title=title,
        url=url,
        description=description,
        image_url=image_url,
        published_at=published_at or datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
