from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from gamenews import config
from gamenews.events import dates as event_dates
from gamenews.events.builder import build_event_candidate
from gamenews.routing import route_items
from gamenews.sources import youtube
from gamenews.tools.replay import _extract_video_id, _targets_matching, run_replay_from_item

logger = logging.getLogger(__name__)

_YOUTUBE_URL_MARKERS = ("youtube.com/watch", "youtu.be/")


class AdminCog(commands.Cog):
    """Owner-only maintenance commands, available as both `!gamenews <name>`
    and `/<name>` slash commands (hybrid commands). Message deletion is
    real and one-way, so every command here defaults to a dry run - it only
    deletes when explicitly told to.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _read_history(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> list[discord.Message] | None:
        """Shared history fetch + friendly error reporting for every
        cleanup-style command. Returns None (already reported to `ctx`) on
        failure so callers can just check for that and return.
        """
        try:
            return [message async for message in channel.history(limit=500)]
        except discord.Forbidden:
            await ctx.send(
                f"I don't have access to read {channel.mention}'s history - check that "
                "**View Channel** and **Read Message History** are allowed for my role "
                "there (channel-specific permission overwrites can block a bot even when "
                "its server-wide permissions allow it)."
            )
            return None
        except discord.HTTPException:
            logger.exception("Failed to read history for channel %s", channel.id)
            await ctx.send(f"Failed to read {channel.mention}'s history - see the logs.")
            return None

    def _is_ours(self, message: discord.Message) -> bool:
        # Persona messages arrive via our own webhooks; assumes no other
        # webhook posts in these channels, reasonable for a private server
        # where only this bot creates webhooks here.
        if message.webhook_id is not None:
            return True
        return self.bot.user is not None and message.author.id == self.bot.user.id

    async def _report_or_delete(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        candidates: list[tuple[discord.Message, str]],
        *,
        do_delete: bool,
        command_hint: str,
    ) -> None:
        if not candidates:
            await ctx.send(f"Nothing to clean up in {channel.mention}.")
            return

        if not do_delete:
            lines = [f"- {msg.jump_url} - {reason}" for msg, reason in candidates[:20]]
            more = f"\n...and {len(candidates) - 20} more" if len(candidates) > 20 else ""
            await ctx.send(
                f"**Dry run** - {len(candidates)} message(s) in {channel.mention} would be deleted:\n"
                + "\n".join(lines)
                + more
                + f"\n\nRun {command_hint} to actually delete them."
            )
            return

        deleted = 0
        for message, _ in candidates:
            try:
                await message.delete()
                deleted += 1
            except discord.HTTPException:
                logger.exception("Failed to delete message %s", message.id)
        await ctx.send(f"Deleted {deleted}/{len(candidates)} message(s) from {channel.mention}.")

    @commands.hybrid_command(name="cleanup")
    @commands.is_owner()
    @app_commands.describe(
        channel="Channel to scan",
        confirm="Actually delete what's found (default: dry run only)",
    )
    async def cleanup(
        self, ctx: commands.Context, channel: discord.TextChannel, confirm: bool = False
    ) -> None:
        """Find this bot's own messages that are stale (older than
        MAX_CONTENT_AGE_DAYS) or no longer match current routing rules."""
        # Slash interactions must get an initial response within 3 seconds
        # or Discord invalidates them ("Unknown interaction"). Scanning
        # history plus a network re-fetch per YouTube link for the
        # mis-routed check easily blows past that, so defer immediately -
        # this also makes ctx.send() below use the deferred followup
        # webhook, which has no such time limit.
        await ctx.defer()
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_CONTENT_AGE_DAYS)

        history = await self._read_history(ctx, channel)
        if history is None:
            return

        candidates: list[tuple[discord.Message, str]] = []
        for message in history:
            if not self._is_ours(message) or not message.embeds:
                continue

            embed = message.embeds[0]
            reason = None
            if embed.timestamp is not None and embed.timestamp < cutoff:
                reason = f"stale (published {embed.timestamp.date()})"
            elif embed.url:
                reason = await self._misrouted_reason(embed.url, channel.id)

            if reason:
                candidates.append((message, reason))

        await self._report_or_delete(
            ctx,
            channel,
            candidates,
            do_delete=confirm,
            command_hint=f"`/cleanup channel:{channel.name} confirm:True`",
        )

    @commands.hybrid_command(name="duplicates")
    @commands.is_owner()
    @app_commands.describe(
        channel="Channel to scan",
        confirm="Actually delete the duplicates found (default: dry run only)",
    )
    async def duplicates(
        self, ctx: commands.Context, channel: discord.TextChannel, confirm: bool = False
    ) -> None:
        """Find repeated posts of the same link in a channel - e.g. a video
        the old bot already posted that got posted again after switching to
        this one. Keeps the oldest copy, flags every later repost."""
        await ctx.defer()  # see cleanup()'s comment - history scans aren't 3-second-fast
        history = await self._read_history(ctx, channel)
        if history is None:
            return

        seen: dict[str, discord.Message] = {}
        candidates: list[tuple[discord.Message, str]] = []
        for message in sorted(history, key=lambda m: m.created_at):
            if not self._is_ours(message) or not message.embeds:
                continue

            embed = message.embeds[0]
            if not embed.url:
                continue

            key = self._dedupe_key(embed.url)
            first = seen.get(key)
            if first is None:
                seen[key] = message
            else:
                candidates.append((message, f"duplicate of {first.jump_url}"))

        await self._report_or_delete(
            ctx,
            channel,
            candidates,
            do_delete=confirm,
            command_hint=f"`/duplicates channel:{channel.name} confirm:True`",
        )

    @commands.hybrid_command(name="backfill")
    @commands.is_owner()
    @app_commands.describe(url="YouTube video URL or ID to process through the live pipeline")
    async def backfill(self, ctx: commands.Context, url: str) -> None:
        """Process a single YouTube video through the exact same routing,
        posting, and event-creation pipeline as a normal poll cycle. For
        when a video scrolls out of a channel's RSS feed (capped at the
        most recent ~15 videos) before any poll ever saw it - a real gap in
        RSS-based polling, not something a restart fixes on its own.
        """
        await ctx.defer()

        try:
            video_id = _extract_video_id(url)
        except ValueError as exc:
            await ctx.send(str(exc))
            return

        item = await youtube.fetch_single(video_id)
        if item is None:
            await ctx.send(f"Could not fetch video `{video_id}` - check the URL.")
            return

        content_poll = self.bot.get_cog("ContentPollCog")
        if content_poll is None:
            await ctx.send("ContentPollCog isn't loaded - can't process this.")
            return

        # Reconstruct the exact routed_item a normal poll would have built,
        # then hand it to the same post_item/maybe_create_events the live
        # poll loop uses - no separate reimplementation to drift out of sync.
        targets = list(_targets_matching(item, self.bot.franchises))
        fetched = {target: [item] for target in targets} if targets else {}
        routed = route_items(self.bot.franchises, fetched) if fetched else []
        if not routed:
            await ctx.send(
                f"**{item.title}** didn't match any configured source/franchise - nothing to do."
            )
            return

        routed_item = routed[0]
        already_posted = [
            channel_id
            for channel_id in routed_item.channel_ids
            if await self.bot.db.is_posted(item.unique_id, channel_id)
        ]

        await content_poll.post_item(routed_item)
        await content_poll.maybe_create_events(routed_item)

        channel_mentions = []
        for channel_id in routed_item.channel_ids:
            channel = self.bot.get_channel(channel_id)
            channel_mentions.append(channel.mention if channel else str(channel_id))

        status = "already posted to" if already_posted else "posted to"
        await ctx.send(
            f"Processed **{item.title}** - {status} {', '.join(channel_mentions)}. "
            "Check the channel(s) for any event that was created."
        )

    def _dedupe_key(self, url: str) -> str:
        """Normalize a link for duplicate comparison. YouTube links compare
        by video ID so URL variants (tracking params, youtu.be vs full
        watch URL) of the same video still match."""
        if any(marker in url for marker in _YOUTUBE_URL_MARKERS):
            try:
                return f"youtube:{_extract_video_id(url)}"
            except ValueError:
                pass
        return url

    async def _misrouted_reason(self, url: str, channel_id: int) -> str | None:
        if not any(marker in url for marker in _YOUTUBE_URL_MARKERS):
            return None  # only YouTube items can be cheaply re-fetched and re-routed

        try:
            video_id = _extract_video_id(url)
            item = await youtube.fetch_single(video_id)
        except Exception:
            return None
        if item is None:
            return None

        result = run_replay_from_item(item, self.bot.franchises)
        if channel_id not in result.routed_channel_ids:
            return "no longer matches current routing rules"
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
