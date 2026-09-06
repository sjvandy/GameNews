from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from gamenews.db import Database
from gamenews.events.builder import EventCandidate
from gamenews.events.lifecycle import EventLifecycleManager
from gamenews.franchises import load_franchises

import pathlib

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "franchises"


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.init()
    yield database
    database.close()


@pytest.fixture
def registry():
    return load_franchises(str(FIXTURES_DIR / "valid.yaml"))


async def _seed_due_ingame_event(db: Database, registry, *, status: str = "SCHEDULED", pinged: bool = False):
    await db.insert_tracked_event(
        guild_scheduled_event_id="123",
        event_type="ingame",
        franchise_key="splatoon-3",
        branded_franchise_key=None,
        source_unique_id="splatoon3ink:splatfest:1",
        name="Splatoon 3 Splatfest: Test",
        start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        end_time=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    if status != "SCHEDULED":
        row = await db.get_tracked_event_by_source("splatoon3ink:splatfest:1")
        await db.update_event_status(row["id"], status)
    if pinged:
        row = await db.get_tracked_event_by_source("splatoon3ink:splatfest:1")
        await db.mark_role_pinged(row["id"])


def _mock_guild(event_status: discord.EventStatus):
    event = MagicMock(spec=discord.ScheduledEvent)
    event.id = 123
    event.status = event_status
    event.start = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.fetch_scheduled_event = AsyncMock(return_value=event)
    return guild, event


def _mock_bot():
    """A bot double whose WebhookManager.get() resolves to a persona
    webhook, so ping delivery is exercised via the webhook path used in
    production rather than the bot's own channel.send fallback."""
    bot = MagicMock()
    webhook = MagicMock()
    webhook.send = AsyncMock()
    bot.webhooks = MagicMock()
    bot.webhooks.get = AsyncMock(return_value=webhook)
    return bot, webhook


def _make_candidate(source_unique_id: str = "splatoon3ink:splatfest:99") -> EventCandidate:
    return EventCandidate(
        event_type="ingame",
        franchise_key="splatoon-3",
        branded_franchise_key=None,
        source_unique_id=source_unique_id,
        name="Splatoon 3 Splatfest: New",
        description="desc",
        start_time=datetime.now(timezone.utc) + timedelta(days=1),
        end_time=datetime.now(timezone.utc) + timedelta(days=2),
        location="Splatoon 3 — Online",
        cover_image_url=None,
    )


@pytest.mark.asyncio
async def test_due_scheduled_event_is_started_and_pinged(db, registry):
    # TC-6: tracked SCHEDULED event with start_time <= now -> event.start()
    # called once, role-ping message sent.
    await _seed_due_ingame_event(db, registry)
    guild, event = _mock_guild(discord.EventStatus.scheduled)
    bot, webhook = _mock_bot()

    manager = EventLifecycleManager(bot, db, registry)
    await manager.maybe_start_due_events(guild)

    event.start.assert_awaited_once()
    webhook.send.assert_awaited_once()

    row = await db.get_tracked_event_by_source("splatoon3ink:splatfest:1")
    assert row["status"] == "ACTIVE"
    assert row["role_pinged_at"] is not None


@pytest.mark.asyncio
async def test_already_active_event_is_not_restarted_or_repinged(db, registry):
    # TC-7: idempotency - ACTIVE + already pinged -> no start(), no duplicate ping.
    await _seed_due_ingame_event(db, registry, status="ACTIVE", pinged=True)
    guild, event = _mock_guild(discord.EventStatus.active)
    bot, webhook = _mock_bot()

    manager = EventLifecycleManager(bot, db, registry)
    await manager.maybe_start_due_events(guild)

    event.start.assert_not_called()
    webhook.send.assert_not_called()


@pytest.mark.asyncio
async def test_create_event_announces_new_event(db, registry):
    # Feature request: an event created for a franchise should immediately
    # post in that franchise's channel and tag its role, not wait for the
    # go-live ping.
    candidate = _make_candidate()
    bot, webhook = _mock_bot()

    created_event = MagicMock(spec=discord.ScheduledEvent)
    created_event.id = 555
    guild = MagicMock(spec=discord.Guild)
    guild.id = 929578849350582302
    guild.create_scheduled_event = AsyncMock(return_value=created_event)

    manager = EventLifecycleManager(bot, db, registry)
    await manager.create_event(guild, candidate)

    guild.create_scheduled_event.assert_awaited_once()
    webhook.send.assert_awaited_once()
    sent_content = webhook.send.call_args.kwargs.get("content", "")
    assert "New event scheduled" in sent_content
    assert candidate.name in sent_content

    row = await db.get_tracked_event_by_source(candidate.source_unique_id)
    assert row["announced_at"] is not None


@pytest.mark.asyncio
async def test_create_event_is_idempotent_once_announced(db, registry):
    candidate = _make_candidate()
    bot, webhook = _mock_bot()
    guild = MagicMock(spec=discord.Guild)
    guild.id = 929578849350582302
    created_event = MagicMock(spec=discord.ScheduledEvent)
    created_event.id = 555
    guild.create_scheduled_event = AsyncMock(return_value=created_event)

    manager = EventLifecycleManager(bot, db, registry)
    await manager.create_event(guild, candidate)
    webhook.send.reset_mock()
    guild.create_scheduled_event.reset_mock()

    await manager.create_event(guild, candidate)

    guild.create_scheduled_event.assert_not_called()
    webhook.send.assert_not_called()


@pytest.mark.asyncio
async def test_create_event_backfills_announcement_for_pre_existing_row(db, registry):
    # Simulates an event created by a version of the bot before the
    # announcement feature existed: a tracked_events row already exists with
    # announced_at NULL, but no announcement was ever sent - e.g. the real
    # Big Run event created before this feature landed.
    candidate = _make_candidate(source_unique_id="splatoon3ink:bigrun:already-there")
    await db.insert_tracked_event(
        guild_scheduled_event_id="999",
        event_type="ingame",
        franchise_key="splatoon-3",
        branded_franchise_key=None,
        source_unique_id=candidate.source_unique_id,
        name=candidate.name,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
    )

    bot, webhook = _mock_bot()
    fetched_event = MagicMock(spec=discord.ScheduledEvent)
    fetched_event.id = 999
    guild = MagicMock(spec=discord.Guild)
    guild.id = 929578849350582302
    guild.fetch_scheduled_event = AsyncMock(return_value=fetched_event)
    guild.create_scheduled_event = AsyncMock()

    manager = EventLifecycleManager(bot, db, registry)
    await manager.create_event(guild, candidate)

    guild.create_scheduled_event.assert_not_called()
    webhook.send.assert_awaited_once()

    row = await db.get_tracked_event_by_source(candidate.source_unique_id)
    assert row["announced_at"] is not None
