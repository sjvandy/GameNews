from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from gamenews.cogs.content_poll import ContentPollCog
from gamenews.routing import RoutedItem
from tests.conftest import make_item


def _mock_bot(registry):
    bot = MagicMock()
    bot.franchises = registry
    bot.get_guild = MagicMock(return_value=MagicMock(spec=discord.Guild))
    bot.db = MagicMock()
    bot.db.mark_posted = AsyncMock()
    bot.event_manager = MagicMock()
    bot.event_manager.create_event = AsyncMock()
    return bot


@pytest.fixture
def cog(registry):
    bot = _mock_bot(registry)
    # ContentPollCog.__init__ starts a tasks.loop, which needs a running
    # event loop it won't get in a sync fixture - construct without it by
    # calling __new__ and setting just what maybe_create_events/post_item need.
    instance = ContentPollCog.__new__(ContentPollCog)
    instance.bot = bot
    return instance


@pytest.mark.asyncio
async def test_maybe_create_events_returns_true_for_matched_ingame_event(cog, registry):
    item = make_item(title="Splatoon 3 Splatfest announcement, runs September 10 to September 12, 2026")
    routed_item = RoutedItem(item=item, channel_ids=[111], matched_franchises=["splatoon-3"])

    result = await cog.maybe_create_events(routed_item)

    assert result is True
    cog.bot.event_manager.create_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_create_events_returns_false_when_nothing_matches(cog, registry):
    item = make_item(title="Super Mario Kart World amiibo unboxing")
    routed_item = RoutedItem(item=item, channel_ids=[999], matched_franchises=[])

    result = await cog.maybe_create_events(routed_item)

    assert result is False
    cog.bot.event_manager.create_event.assert_not_called()


@pytest.mark.asyncio
async def test_mark_all_posted_marks_every_channel(cog):
    item = make_item(unique_id="youtube:xyz")
    routed_item = RoutedItem(item=item, channel_ids=[111, 222], matched_franchises=[])

    await cog.mark_all_posted(routed_item)

    assert cog.bot.db.mark_posted.await_count == 2
    cog.bot.db.mark_posted.assert_any_await("youtube:xyz", 111, "youtube")
    cog.bot.db.mark_posted.assert_any_await("youtube:xyz", 222, "youtube")
