from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from gamenews import config
from gamenews.events import classify
from gamenews.events import dates as event_dates
from gamenews.events.builder import build_event_candidate
from gamenews.routing import RoutedItem, collect_fetch_targets, fetch_all, route_items
from gamenews.sources import ContentItem

logger = logging.getLogger(__name__)

COLORS = {
    "youtube": discord.Colour(0xFF0000),
    "instagram": discord.Colour(0xE1306C),
    "nintendo_news": discord.Colour(0xE60012),
}

SOURCE_LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "nintendo_news": "Nintendo News",
}


def build_embed(item: ContentItem) -> discord.Embed:
    color = COLORS.get(item.source, discord.Colour.blurple())
    label = SOURCE_LABELS.get(item.source, item.source)

    embed = discord.Embed(
        title=item.title[:256],
        url=item.url,
        description=item.description[:4096] if item.description else None,
        color=color,
        timestamp=item.published_at,
    )
    embed.set_author(name=label)

    if item.image_url:
        embed.set_image(url=item.image_url)

    if item.source == "youtube":
        views = item.extra.get("views", 0)
        if views:
            embed.add_field(name="Views", value=f"{views:,}", inline=True)
    elif item.source == "instagram":
        likes = item.extra.get("likes", 0)
        if likes:
            embed.add_field(name="Likes", value=f"{likes:,}", inline=True)
        if item.extra.get("is_video"):
            embed.add_field(name="Type", value="Video", inline=True)

    return embed


def is_stale(item: ContentItem, *, max_age_days: int, now: datetime | None = None) -> bool:
    """Content older than max_age_days is never treated as "new" - not
    posted, not turned into an event candidate - even the very first time
    it's seen. Without this, an old video sitting in a channel's last-15
    RSS window (e.g. a months-old announcement for an event long over) gets
    blasted out as if it just happened. Unknown age (no published_at) is
    never treated as stale - better to post than to wrongly suppress."""
    if item.published_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return item.published_at < now - timedelta(days=max_age_days)


async def scan_channel_history(channel: discord.TextChannel, limit: int = 500) -> set[str]:
    """Scan channel history and extract URLs already posted, so a brand-new
    dedup DB doesn't cause a flood of reposts on first boot."""
    posted_urls: set[str] = set()
    try:
        async for message in channel.history(limit=limit):
            for embed in message.embeds:
                if embed.url:
                    posted_urls.add(embed.url)
            for word in message.content.split():
                if word.startswith(("https://", "http://")):
                    posted_urls.add(word)
        logger.info("Scanned %d URLs from #%s history", len(posted_urls), channel.name)
    except discord.Forbidden:
        logger.warning("Cannot read #%s history - missing Read Message History permission", channel.name)
    except discord.HTTPException:
        logger.exception("Failed to scan #%s history", channel.name)
    return posted_urls


class ContentPollCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.poll_sources.change_interval(minutes=config.POLL_INTERVAL_MINUTES)
        self.poll_sources.start()

    def cog_unload(self) -> None:
        self.poll_sources.cancel()

    @tasks.loop(minutes=15)
    async def poll_sources(self) -> None:
        logger.info("Polling all sources...")
        registry = self.bot.franchises
        targets = collect_fetch_targets(registry)
        fetched = await fetch_all(targets)
        routed = route_items(registry, fetched)

        await self._seed_newsroom_if_needed(routed)

        for routed_item in routed:
            if is_stale(routed_item.item, max_age_days=config.MAX_CONTENT_AGE_DAYS):
                logger.info(
                    "Skipping stale content (published %s, older than %dd): %s",
                    routed_item.item.published_at,
                    config.MAX_CONTENT_AGE_DAYS,
                    routed_item.item.title,
                )
                await self.mark_all_posted(routed_item)
                continue

            # Check events first: if this item is Direct/event-worthy, its
            # own announcement (with a link back to the source) is the one
            # message that should appear - posting the plain content embed
            # too would just be a redundant second message in the same
            # channel about the same thing.
            event_created = await self.maybe_create_events(routed_item)
            if event_created:
                await self.mark_all_posted(routed_item)
            else:
                await self.post_item(routed_item)

    async def mark_all_posted(self, routed_item: RoutedItem) -> None:
        for channel_id in routed_item.channel_ids:
            await self.bot.db.mark_posted(
                routed_item.item.unique_id, channel_id, routed_item.item.source
            )

    async def _seed_newsroom_if_needed(self, routed: list[RoutedItem]) -> None:
        newsroom_id = self.bot.franchises.media_events.fallback_channel_id
        if await self.bot.db.has_any_posting(newsroom_id):
            return

        channel = self.bot.get_channel(newsroom_id)
        if channel is None:
            return

        logger.info("First run detected for #%s - scanning history before posting", channel.name)
        posted_urls = await scan_channel_history(channel)

        for routed_item in routed:
            if newsroom_id in routed_item.channel_ids and routed_item.item.url in posted_urls:
                await self.bot.db.mark_posted(
                    routed_item.item.unique_id, newsroom_id, routed_item.item.source
                )

    async def post_item(self, routed_item: RoutedItem) -> None:
        """Public: also called by AdminCog's /backfill for a single video
        processed outside the normal poll cycle (e.g. one that scrolled out
        of a channel's RSS window before a poll ever saw it)."""
        item = routed_item.item
        for channel_id in routed_item.channel_ids:
            if await self.bot.db.is_posted(item.unique_id, channel_id):
                continue

            embed = build_embed(item)
            name, avatar_path = self.bot.franchises.persona_for_channel(channel_id)
            webhook = await self.bot.webhooks.get(channel_id, name, avatar_path)

            try:
                if webhook is not None:
                    await webhook.send(embed=embed)
                else:
                    # Missing Manage Webhooks or the channel is gone - post as
                    # the bot itself rather than silently dropping the item.
                    channel = self.bot.get_channel(channel_id)
                    if channel is None:
                        logger.error("Channel %s not found - check franchises.yaml", channel_id)
                        continue
                    await channel.send(embed=embed)
                await self.bot.db.mark_posted(item.unique_id, channel_id, item.source)
            except discord.HTTPException:
                logger.exception("Failed to send embed for %s to channel %s", item.unique_id, channel_id)

    async def maybe_create_events(self, routed_item: RoutedItem) -> bool:
        """Public: see post_item's docstring.

        Returns True if this item was event-worthy (an in-game or media
        event was matched, regardless of whether create_event() treats it
        as new or already-tracked) - the caller uses this to skip the plain
        content post, since the event's own announcement (linking back to
        the source) is the one message that should appear for it.
        """
        item = routed_item.item
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return False

        event_created = False

        for franchise_key in routed_item.matched_franchises:
            franchise = self.bot.franchises.get(franchise_key)
            if franchise is None or not classify.classify_ingame(item, franchise):
                continue

            date_range = event_dates.extract_date_range(
                f"{item.title} {item.description}",
                default_duration=event_dates.DEFAULT_INGAME_DURATION,
            )
            if date_range is None:
                logger.warning(
                    "In-game event candidate with unparseable dates - skipping: %s", item.title
                )
                continue

            candidate = build_event_candidate(item, "ingame", date_range, franchise=franchise)
            await self.bot.event_manager.create_event(guild, candidate)
            event_created = True

        media_classification = classify.classify_media(item, self.bot.franchises)
        if media_classification is None or not media_classification.is_direct:
            return event_created

        date_range = event_dates.extract_date_range(
            f"{item.title} {item.description}",
            default_duration=event_dates.DEFAULT_MEDIA_DURATION,
        )
        if date_range is None:
            logger.warning("Media event candidate with unparseable dates - skipping: %s", item.title)
            return event_created

        branded_franchise = self.bot.franchises.get(media_classification.branded_franchise_key)
        candidate = build_event_candidate(
            item,
            "media",
            date_range,
            franchise=branded_franchise,
            branded_franchise_key=media_classification.branded_franchise_key,
        )
        await self.bot.event_manager.create_event(guild, candidate)
        return True

    @poll_sources.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ContentPollCog(bot))
