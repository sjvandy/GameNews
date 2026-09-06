from __future__ import annotations

from datetime import datetime, timezone

from gamenews.sources.nintendo_news import _build_item, _extract_articles

# Mirrors the real shape found live on nintendo.com/us/whatsnew/ as of this
# writing: articles live in a normalized Apollo Client cache
# (initialApolloState), not a plain list anywhere in pageProps - the
# original scraper never found this and silently returned zero articles
# every single run.
REAL_SHAPE_ARTICLE = {
    "__typename": "NewsArticle",
    "id": "2f5OUe4ags49ctI4tfRUwK",
    "locale": "en_US",
    "title": "Nintendo and Laced Records - The Legend of Zelda: Breath of the Wild vinyl soundtrack collection available today!",
    "body": {
        "__typename": "RichText",
        'text({"characterLimit":250})': "The score from the epic adventure in a collectible double LP or premium 8-LP box set now available.",
    },
    "media": {
        "__typename": "CloudinaryAsset",
        "publicId": "ncom/en_US/articles/2025/some-article/cover-image",
        "resourceType": "image",
    },
    "publishDate": "2026-09-04T16:00:00.000Z",
    'url({"relative":true})': "/us/whatsnew/nintendo-and-laced-records-the-legend-of-zelda-breath-of-the-wild-vinyl-soundtrack-collection-available-today-switch/",
    "slug": "nintendo-and-laced-records-the-legend-of-zelda-breath-of-the-wild-vinyl-soundtrack-collection-available-today-switch",
}


def _apollo_page_props(articles: list[dict]) -> dict:
    apollo = {}
    for article in articles:
        key = f'NewsArticle:{{"id":"{article["id"]}","locale":"en_US"}}'
        apollo[key] = article
    apollo["ContentTag:articleCategoryGameNews"] = {"__typename": "ContentTag"}  # unrelated noise
    return {"content": {"navContent": {}}, "initialApolloState": apollo}


def test_extract_articles_finds_apollo_cached_news_articles():
    page_props = _apollo_page_props([REAL_SHAPE_ARTICLE])
    articles = _extract_articles(page_props)
    assert len(articles) == 1
    assert articles[0]["id"] == "2f5OUe4ags49ctI4tfRUwK"


def test_extract_articles_ignores_non_article_apollo_entries():
    page_props = _apollo_page_props([REAL_SHAPE_ARTICLE])
    articles = _extract_articles(page_props)
    assert all(a.get("__typename") == "NewsArticle" for a in articles)


def test_build_item_from_real_shape():
    item = _build_item(REAL_SHAPE_ARTICLE)
    assert item is not None
    assert item.unique_id == "nintendo:2f5OUe4ags49ctI4tfRUwK"
    assert item.url == (
        "https://www.nintendo.com/us/whatsnew/"
        "nintendo-and-laced-records-the-legend-of-zelda-breath-of-the-wild-vinyl-soundtrack-collection-available-today-switch/"
    )
    assert item.description.startswith("The score from the epic adventure")
    assert item.image_url == (
        "https://assets.nintendo.com/image/upload/ar_16:9,c_lpad/b_white/f_auto/q_auto/dpr_1.0/c_scale,w_500/"
        "ncom/en_US/articles/2025/some-article/cover-image"
    )
    assert item.published_at == datetime(2026, 9, 4, 16, 0, 0, tzinfo=timezone.utc)


def test_build_item_falls_back_to_slug_when_no_relative_url_field():
    article = dict(REAL_SHAPE_ARTICLE)
    del article['url({"relative":true})']
    item = _build_item(article)
    assert item is not None
    assert item.url.endswith(f"/us/whatsnew/{article['slug']}/")


def test_build_item_returns_none_without_an_id():
    article = dict(REAL_SHAPE_ARTICLE)
    del article["id"]
    assert _build_item(article) is None
