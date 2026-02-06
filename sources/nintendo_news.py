from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiohttp
from bs4 import BeautifulSoup

import config
from sources import ContentItem

logger = logging.getLogger(__name__)

IMAGE_BASE = (
    "https://assets.nintendo.com/image/upload"
    "/ar_16:9,c_lpad/b_white/f_auto/q_auto/dpr_1.0/c_scale,w_500"
)


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def fetch() -> list[ContentItem]:
    """Fetch recent articles from Nintendo's news page via __NEXT_DATA__."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(config.NINTENDO_NEWS_URL, headers=headers) as resp:
                resp.raise_for_status()
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag or not script_tag.string:
            logger.warning("Nintendo News: __NEXT_DATA__ script tag not found")
            return []

        data = json.loads(script_tag.string)

        # Navigate the Next.js page props to find articles
        page_props = data.get("props", {}).get("pageProps", {})
        articles = _extract_articles(page_props)

        if not articles:
            logger.warning("Nintendo News: no articles found in page data")
            return []

        items: list[ContentItem] = []
        for article in articles:
            entry_id = article.get("id", article.get("contentfulEntryId", ""))
            if not entry_id:
                continue

            title = article.get("title", "Untitled")
            slug = article.get("slug", article.get("url", ""))
            url = slug if slug.startswith("http") else f"https://www.nintendo.com{slug}"
            summary = article.get("description", article.get("subtitle", ""))
            published = _parse_date(article.get("publishDate", article.get("date", "")))

            image_url = ""
            public_id = article.get("publicId", "")
            if not public_id:
                image = article.get("image", {})
                if isinstance(image, dict):
                    public_id = image.get("publicId", "")
            if public_id:
                image_url = f"{IMAGE_BASE}/{public_id}"

            items.append(
                ContentItem(
                    source="nintendo_news",
                    unique_id=f"nintendo:{entry_id}",
                    title=title,
                    url=url,
                    description=summary[:300],
                    image_url=image_url,
                    published_at=published,
                    extra={"entry_id": entry_id},
                )
            )

        logger.info("Nintendo News: fetched %d items", len(items))
        return items

    except Exception:
        logger.exception("Nintendo News: fetch failed")
        return []


def _extract_articles(page_props: dict) -> list[dict]:
    """Try multiple known paths to locate the article list in __NEXT_DATA__."""
    # Direct articles list
    if "articles" in page_props:
        return page_props["articles"]

    # Nested under initialApolloState or similar
    for key in ("initialData", "data", "content"):
        if key in page_props and isinstance(page_props[key], dict):
            nested = page_props[key]
            for sub_key in ("articles", "items", "posts", "entries"):
                if sub_key in nested and isinstance(nested[sub_key], list):
                    return nested[sub_key]

    # Fallback: search for any list of dicts with a 'title' key
    for value in page_props.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if "title" in value[0]:
                return value

    return []
