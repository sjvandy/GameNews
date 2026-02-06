from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ContentItem:
    source: str  # "youtube" | "nintendo_news" | "instagram"
    unique_id: str  # Prefixed ID for dedup (e.g. "youtube:abc123")
    title: str
    url: str
    description: str
    image_url: str
    published_at: datetime | None = None
    extra: dict = field(default_factory=dict)
