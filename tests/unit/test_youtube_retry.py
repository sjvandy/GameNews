from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from gamenews.sources import youtube

FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry><yt:videoId>abc123abc12</yt:videoId><title>State of Play</title>
  <link href="https://www.youtube.com/watch?v=abc123abc12"/>
  <published>2026-09-20T00:00:00+00:00</published></entry>
</feed>"""


def _response(status: int):
    resp = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            MagicMock(), (), status=status
        )
    resp.text = AsyncMock(return_value=FEED)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _patch_session(monkeypatch, statuses: list[int]):
    session = MagicMock()
    session.get = MagicMock(side_effect=[_response(s) for s in statuses])
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(youtube.aiohttp, "ClientSession", MagicMock(return_value=session_ctx))
    monkeypatch.setattr(youtube.asyncio, "sleep", AsyncMock())
    return session


@pytest.mark.asyncio
async def test_fetch_retries_through_intermittent_404s(monkeypatch):
    # Real behavior: YouTube's RSS endpoint 404s ~half the time for valid
    # channels (seen for PlayStation's), then succeeds on a later try.
    session = _patch_session(monkeypatch, [404, 500, 200])

    items = await youtube.fetch("UC-2Y8dQb0S6DtpxNgAKoJKA")

    assert [i.title for i in items] == ["State of Play"]
    assert session.get.call_count == 3


@pytest.mark.asyncio
async def test_fetch_gives_up_after_max_attempts(monkeypatch):
    session = _patch_session(monkeypatch, [404] * youtube.RSS_ATTEMPTS)

    items = await youtube.fetch("UC-2Y8dQb0S6DtpxNgAKoJKA")

    assert items == []
    assert session.get.call_count == youtube.RSS_ATTEMPTS
