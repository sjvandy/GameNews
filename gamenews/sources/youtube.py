from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from gamenews.sources import ContentItem

logger = logging.getLogger(__name__)

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
OEMBED_URL = "https://www.youtube.com/oembed"
WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"


async def fetch(channel_id: str) -> list[ContentItem]:
    """Fetch recent videos from a YouTube channel's RSS feed."""
    try:
        url = RSS_URL_TEMPLATE.format(channel_id=channel_id)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
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
                    url=entry.get("link", WATCH_URL_TEMPLATE.format(video_id=video_id)),
                    description=description[:300],
                    image_url=thumbnail,
                    published_at=published,
                    extra={"views": views, "video_id": video_id, "channel_id": channel_id},
                )
            )

        logger.info("YouTube (%s): fetched %d items", channel_id, len(items))
        return items

    except Exception:
        logger.exception("YouTube (%s): fetch failed", channel_id)
        return []


async def fetch_single(video_id: str) -> ContentItem | None:
    """Fetch a single video by ID, for videos outside the RSS feed's recent window.

    Combines the oEmbed endpoint (title/author/thumbnail, no key required) with a
    scrape of the watch page's meta tags (description/published date) - mirrors the
    __NEXT_DATA__ scraping style already used in nintendo_news.py, no new API key.
    """
    watch_url = WATCH_URL_TEMPLATE.format(video_id=video_id)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                OEMBED_URL, params={"url": watch_url, "format": "json"}
            ) as resp:
                if resp.status != 200:
                    logger.warning("YouTube oEmbed failed for %s: HTTP %d", video_id, resp.status)
                    return None
                oembed = await resp.json()

            title = oembed.get("title", "Untitled")
            thumbnail = oembed.get("thumbnail_url", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
            channel_id = None

            description = ""
            published = None
            async with session.get(watch_url) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    desc_tag = soup.find("meta", property="og:description")
                    if desc_tag and desc_tag.get("content"):
                        description = desc_tag["content"]
                    date_tag = soup.find("meta", itemprop="datePublished")
                    if date_tag and date_tag.get("content"):
                        try:
                            published = datetime.fromisoformat(date_tag["content"]).astimezone(timezone.utc)
                        except ValueError:
                            published = None

                    # Neither oEmbed's author_url nor any <meta> tag exposes the
                    # channel ID for @handle-based channels (most official
                    # channels today) - it's only present embedded in the page's
                    # inline JSON, e.g. "channelId":"UCxxxx".
                    channel_match = re.search(r'"channelId":"([\w-]+)"', html)
                    if channel_match:
                        channel_id = channel_match.group(1)

        return ContentItem(
            source="youtube",
            unique_id=f"youtube:{video_id}",
            title=title,
            url=watch_url,
            description=description[:300],
            image_url=thumbnail,
            published_at=published,
            extra={"views": 0, "video_id": video_id, "channel_id": channel_id},
        )

    except Exception:
        logger.exception("YouTube: fetch_single failed for %s", video_id)
        return None
