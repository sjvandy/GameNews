from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp
import feedparser

import config
from sources import ContentItem

logger = logging.getLogger(__name__)


async def fetch() -> list[ContentItem]:
    """Fetch recent videos from Nintendo's YouTube RSS feed."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(config.YOUTUBE_RSS_URL) as resp:
                resp.raise_for_status()
                text = await resp.text()

        feed = feedparser.parse(text)
        items: list[ContentItem] = []

        for entry in feed.entries:
            video_id = entry.get("yt_videoid", "")
            if not video_id:
                continue

            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            views = 0
            stats = entry.get("media_statistics")
            if stats:
                views = int(stats.get("views", 0))

            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            media_group = entry.get("media_group")
            if media_group:
                thumbnails = media_group.get("media_thumbnail", [])
                if thumbnails:
                    thumbnail = thumbnails[0].get("url", thumbnail)

            description = ""
            if media_group:
                desc_list = media_group.get("media_description", [])
                if desc_list:
                    description = desc_list[0].get("content", "")
            if not description:
                description = entry.get("summary", "")

            items.append(
                ContentItem(
                    source="youtube",
                    unique_id=f"youtube:{video_id}",
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link", f"https://www.youtube.com/watch?v={video_id}"),
                    description=description[:300],
                    image_url=thumbnail,
                    published_at=published,
                    extra={"views": views, "video_id": video_id},
                )
            )

        logger.info("YouTube: fetched %d items", len(items))
        return items

    except Exception:
        logger.exception("YouTube: fetch failed")
        return []
