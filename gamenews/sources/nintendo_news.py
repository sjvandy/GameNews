from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiohttp
from bs4 import BeautifulSoup

from gamenews import config
from gamenews.sources import ContentItem

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


def _find_prefixed(mapping: dict | None, prefix: str):
    """Apollo Client's normalized cache stores a field called with query
    arguments under a literal key like 'text({"characterLimit":250})', not
    just 'text' - this finds such a key by prefix instead of guessing the
    exact argument serialization, which could change independently of the
    field itself."""
    if not isinstance(mapping, dict):
        return None
    for key, value in mapping.items():
        if key.startswith(prefix):
            return value
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

        page_props = data.get("props", {}).get("pageProps", {})
        articles = _extract_articles(page_props)

        if not articles:
            logger.warning("Nintendo News: no articles found in page data")
            return []

        items = [item for item in (_build_item(article) for article in articles) if item is not None]

        logger.info("Nintendo News: fetched %d items", len(items))
        return items

    except Exception:
        logger.exception("Nintendo News: fetch failed")
        return []


def _build_item(article: dict) -> ContentItem | None:
    entry_id = article.get("id", article.get("contentfulEntryId", ""))
    if not entry_id:
        return None

    title = article.get("title", "Untitled")

    # Apollo's cache stores the relative URL under a literal
    # 'url({"relative":true})' key; "slug" alone (e.g. "some-article-title")
    # is missing the "/us/whatsnew/" path Nintendo actually serves it under.
    relative_url = _find_prefixed(article, "url(")
    slug = article.get("slug", article.get("url", ""))
    if relative_url:
        url = relative_url if relative_url.startswith("http") else f"https://www.nintendo.com{relative_url}"
    elif slug:
        url = slug if slug.startswith("http") else f"https://www.nintendo.com/us/whatsnew/{slug}/"
    else:
        return None

    summary = _find_prefixed(article.get("body"), "text(") or article.get(
        "description", article.get("subtitle", "")
    )
    published = _parse_date(article.get("publishDate", article.get("date", "")))

    image_url = ""
    public_id = article.get("publicId", "")
    if not public_id:
        # "media" is the current Apollo field name; "image" kept for
        # compatibility with the older shape this replaced.
        media = article.get("media", article.get("image", {}))
        if isinstance(media, dict):
            public_id = media.get("publicId", "")
    if public_id:
        image_url = f"{IMAGE_BASE}/{public_id}"

    return ContentItem(
        source="nintendo_news",
        unique_id=f"nintendo:{entry_id}",
        title=title,
        url=url,
        description=summary[:300],
        image_url=image_url,
        published_at=published,
        extra={"entry_id": entry_id},
    )


def _extract_articles(page_props: dict) -> list[dict]:
    """Locate the article list in __NEXT_DATA__.

    As of this writing, Nintendo stores articles in a normalized Apollo
    Client cache (props.pageProps.initialApolloState), keyed like
    'NewsArticle:{"id":"...","locale":"en_US"}' - not as a plain list
    anywhere in pageProps. The older shapes below are kept as a fallback in
    case that changes again, but are unlikely to ever match now.
    """
    apollo = page_props.get("initialApolloState")
    if isinstance(apollo, dict):
        articles = [
            value
            for key, value in apollo.items()
            if key.startswith("NewsArticle:") and isinstance(value, dict)
        ]
        if articles:
            return articles

    if "articles" in page_props:
        return page_props["articles"]

    for key in ("initialData", "data", "content"):
        if key in page_props and isinstance(page_props[key], dict):
            nested = page_props[key]
            for sub_key in ("articles", "items", "posts", "entries"):
                if sub_key in nested and isinstance(nested[sub_key], list):
                    return nested[sub_key]

    for value in page_props.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            if "title" in value[0]:
                return value

    return []
