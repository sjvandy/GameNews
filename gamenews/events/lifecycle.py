from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp
import discord

from gamenews.db import Database
from gamenews.events.builder import EventCandidate
from gamenews.franchises import FranchiseRegistry

logger = logging.getLogger(__name__)


class EventLifecycleManager:
    """Owns every Discord Scheduled Event mutation: creation (FR-4/FR-5),
    auto-start (FR-6), and role-ping-on-ACTIVE (FR-7), all backed by
    `tracked_events` so state survives a restart.
    """

    def __init__(self, bot: discord.Client, db: Database, registry: FranchiseRegistry) -> None:
        self.bot = bot
        self.db = db
        self.registry = registry

    async def create_event(self, guild: discord.Guild, candidate: EventCandidate) -> None:
        existing = await self.db.get_tracked_event_by_source(candidate.source_unique_id)
        if existing is not None:
            # Covers both an ordinary re-poll of an already-created event, and
            # - since this check runs regardless of *why* the row exists -
            # backfilling the announcement for an event that was created
            # before this feature existed (announced_at is NULL either way).
            if existing["announced_at"] is None:
                try:
                    event = await guild.fetch_scheduled_event(int(existing["guild_scheduled_event_id"]))
                except discord.HTTPException:
                    logger.exception(
                        "Could not fetch existing event %s to backfill its announcement",
                        existing["guild_scheduled_event_id"],
                    )
                    return
                await self._announce_created_event(candidate, event, guild.id)
                await self.db.mark_announced(existing["id"])
            else:
                logger.debug("Event already tracked for %s - skipping", candidate.source_unique_id)
            return

        image_bytes = await self._download_image(candidate.cover_image_url)

        try:
            event = await guild.create_scheduled_event(
                name=candidate.name,
                description=candidate.description,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location=candidate.location,
                image=image_bytes,
            )
        except discord.HTTPException:
            logger.exception("Failed to create scheduled event for %s", candidate.source_unique_id)
            return

        row_id = await self.db.insert_tracked_event(
            guild_scheduled_event_id=str(event.id),
            event_type=candidate.event_type,
            franchise_key=candidate.franchise_key,
            branded_franchise_key=candidate.branded_franchise_key,
            source_unique_id=candidate.source_unique_id,
            name=candidate.name,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
        )
        logger.info("Created scheduled event %s: %s", event.id, candidate.name)

        await self._announce_created_event(candidate, event, guild.id)
        await self.db.mark_announced(row_id)

    async def refresh_event(self, guild: discord.Guild, row, candidate: EventCandidate) -> None:
        """Push a freshly-derived candidate's fields onto its already
        -tracked Discord event (name/description/start/end/cover image) and
        update the tracked row to match. For /refresh: fixing an event whose
        source content changed, or whose original extraction was wrong (e.g.
        the date-only default-midnight time before broadcast-time parsing
        existed) - always safe to call, since it only edits fields already
        owned by this event, never creates or deletes.
        """
        event = await guild.fetch_scheduled_event(int(row["guild_scheduled_event_id"]))
        image_bytes = await self._download_image(candidate.cover_image_url)
        await event.edit(
            name=candidate.name,
            description=candidate.description,
            start_time=candidate.start_time,
            end_time=candidate.end_time,
            image=image_bytes,
        )
        await self.db.update_event_fields(
            row["id"], name=candidate.name, start_time=candidate.start_time, end_time=candidate.end_time
        )

    async def _download_image(self, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.read()
        except Exception:
            logger.warning("Could not download cover image %s - creating event without one", url)
            return None

    def _ping_targets(
        self, event_type: str, franchise_key: str | None, branded_franchise_key: str | None
    ) -> list[tuple[int, int | None]]:
        """Where an event's announcements go: its own franchise channel+role
        for an in-game event; for a media event, a general notice in the
        fallback channel plus - if branded (FR-5) - an additional ping in
        that franchise's own channel. Shared by the creation announcement
        and the go-live ping, so both reach the same audience.
        """
        targets: list[tuple[int, int | None]] = []

        if event_type == "ingame":
            franchise = self.registry.get(franchise_key)
            if franchise:
                targets.append((franchise.channel_id, franchise.role_id))
            return targets

        targets.append((self.registry.media_events.fallback_channel_id, None))
        if branded_franchise_key:
            branded = self.registry.get(branded_franchise_key)
            if branded:
                targets.append((branded.channel_id, branded.role_id))
        return targets

    async def _post_to_channel(self, channel_id: int, content: str) -> None:
        name, avatar_path = self.registry.persona_for_channel(channel_id)
        webhook = await self.bot.webhooks.get(channel_id, name, avatar_path)

        try:
            if webhook is not None:
                await webhook.send(content=content)
                return
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                logger.error("Channel %s not found", channel_id)
                return
            await channel.send(content)
        except discord.HTTPException:
            logger.exception("Failed to post to channel %s", channel_id)

    async def _announce_created_event(
        self, candidate: EventCandidate, event: discord.ScheduledEvent, guild_id: int
    ) -> None:
        event_url = f"https://discord.com/events/{guild_id}/{event.id}"
        for channel_id, role_id in self._ping_targets(
            candidate.event_type, candidate.franchise_key, candidate.branded_franchise_key
        ):
            mention = f"<@&{role_id}> " if role_id else ""
            await self._post_to_channel(
                channel_id, f"{mention}📅 New event scheduled: **{candidate.name}**\n{event_url}"
            )

    async def _send_live_ping(self, channel_id: int, role_id: int | None, event_name: str) -> None:
        mention = f"<@&{role_id}> " if role_id else ""
        await self._post_to_channel(channel_id, f"{mention}🔴 **{event_name}** is live now!")

    async def maybe_start_due_events(self, guild: discord.Guild) -> None:
        """FR-6/FR-7: flip SCHEDULED events past their start time to ACTIVE and
        ping roles, exactly once (TC-6/TC-7). DB status is authoritative but
        Discord's live status is re-checked defensively, since Discord never
        auto-transitions SCHEDULED->ACTIVE itself but a human could have
        started/cancelled the event manually via the Discord UI.
        """
        due = await self.db.get_due_scheduled_events(datetime.now(timezone.utc))
        for row in due:
            try:
                event = await guild.fetch_scheduled_event(int(row["guild_scheduled_event_id"]))
            except discord.NotFound:
                logger.warning(
                    "Tracked event %s no longer exists on Discord - marking cancelled",
                    row["guild_scheduled_event_id"],
                )
                await self.db.update_event_status(row["id"], "CANCELED")
                continue
            except discord.HTTPException:
                logger.exception("Failed to fetch scheduled event %s", row["guild_scheduled_event_id"])
                continue

            if event.status == discord.EventStatus.scheduled:
                try:
                    await event.start()
                except discord.HTTPException:
                    logger.exception("Failed to start event %s", event.id)
                    continue
                await self.db.update_event_status(row["id"], "ACTIVE")
            elif event.status == discord.EventStatus.active:
                if row["status"] != "ACTIVE":
                    await self.db.update_event_status(row["id"], "ACTIVE")
            elif event.status in (discord.EventStatus.completed, discord.EventStatus.ended):
                await self.db.update_event_status(row["id"], "COMPLETED")
                continue
            elif event.status == discord.EventStatus.cancelled:
                await self.db.update_event_status(row["id"], "CANCELED")
                continue

            if row["role_pinged_at"] is None:
                targets = self._ping_targets(
                    row["event_type"], row["franchise_key"], row["branded_franchise_key"]
                )
                for channel_id, role_id in targets:
                    await self._send_live_ping(channel_id, role_id, row["name"])
                await self.db.mark_role_pinged(row["id"])
