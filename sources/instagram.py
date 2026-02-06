from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

import config
from sources import ContentItem

logger = logging.getLogger(__name__)

API_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
APP_ID = "936619743392459"


async def fetch() -> list[ContentItem]:
    """Fetch recent posts from Nintendo's Instagram via undocumented web API.

    This endpoint is fragile and may return 401/403/429 at any time.
    Controlled by the ENABLE_INSTAGRAM config flag.
    """
    if not config.ENABLE_INSTAGRAM:
        logger.debug("Instagram: disabled via config")
        return []

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "x-ig-app-id": APP_ID,
        }
        params = {"username": config.INSTAGRAM_USERNAME}

        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, headers=headers, params=params) as resp:
                if resp.status in (401, 403, 429):
                    logger.warning(
                        "Instagram: HTTP %d - consider setting ENABLE_INSTAGRAM=false",
                        resp.status,
                    )
                    return []
                resp.raise_for_status()
                data = await resp.json()

        user = data.get("data", {}).get("user", {})
        edges = (
            user.get("edge_owner_to_timeline_media", {}).get("edges", [])
        )

        items: list[ContentItem] = []
        for edge in edges:
            node = edge.get("node", {})
            shortcode = node.get("shortcode", "")
            if not shortcode:
                continue

            caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
            caption = ""
            if caption_edges:
                caption = caption_edges[0].get("node", {}).get("text", "")

            is_video = node.get("is_video", False)
            title_prefix = "[Video] " if is_video else ""
            title = f"{title_prefix}{caption[:100]}" if caption else f"{title_prefix}New post"

            timestamp = node.get("taken_at_timestamp")
            published = None
            if timestamp:
                published = datetime.fromtimestamp(timestamp, tz=timezone.utc)

            thumbnail = node.get("thumbnail_src", node.get("display_url", ""))
            likes = node.get("edge_liked_by", {}).get("count", 0)

            items.append(
                ContentItem(
                    source="instagram",
                    unique_id=f"instagram:{shortcode}",
                    title=title,
                    url=f"https://www.instagram.com/p/{shortcode}/",
                    description=caption[:300],
                    image_url=thumbnail,
                    published_at=published,
                    extra={
                        "is_video": is_video,
                        "likes": likes,
                        "shortcode": shortcode,
                    },
                )
            )

        logger.info("Instagram: fetched %d items", len(items))
        return items

    except Exception:
        logger.exception("Instagram: fetch failed")
        return []
