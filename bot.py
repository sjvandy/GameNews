from __future__ import annotations

import asyncio
import json
import logging
import pathlib
from datetime import datetime, timezone

import discord
from discord.ext import tasks

import config
from sources import ContentItem
from sources import youtube, nintendo_news, instagram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True  # Needed to read embed URLs from history
client = discord.Client(intents=intents)

# ---------------------------------------------------------------------------
# Seen-posts persistence
# ---------------------------------------------------------------------------

seen_path = pathlib.Path(config.SEEN_POSTS_PATH)


def load_seen() -> set[str]:
    if not seen_path.exists():
        return set()
    try:
        data = json.loads(seen_path.read_text())
        if isinstance(data, list):
            return set(data)
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupted %s - resetting to empty", seen_path)
    return set()


def save_seen(seen: set[str]) -> None:
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen), indent=2))


async def scan_channel_history(channel: discord.TextChannel, limit: int = 500) -> set[str]:
    """Scan channel history and extract URLs from embeds and messages.

    Returns a set of URLs that have already been posted to the channel.
    """
    posted_urls: set[str] = set()
    try:
        async for message in channel.history(limit=limit):
            # Check embed URLs
            for embed in message.embeds:
                if embed.url:
                    posted_urls.add(embed.url)
            # Check message content for URLs
            for word in message.content.split():
                if word.startswith(("https://", "http://")):
                    posted_urls.add(word)
        logger.info("Scanned %d URLs from channel history", len(posted_urls))
    except discord.Forbidden:
        logger.warning("Cannot read channel history - missing Read Message History permission")
    except discord.HTTPException:
        logger.exception("Failed to scan channel history")
    return posted_urls


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------

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

    # Source-specific fields
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


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

@tasks.loop(minutes=config.POLL_INTERVAL_MINUTES)
async def poll_sources() -> None:
    logger.info("Polling all sources...")

    results = await asyncio.gather(
        youtube.fetch(),
        nintendo_news.fetch(),
        instagram.fetch(),
        return_exceptions=True,
    )

    all_items: list[ContentItem] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.error("Source raised exception: %s", result)
            continue
        all_items.extend(result)

    seen = load_seen()
    first_run = len(seen) == 0 and len(all_items) > 0

    channel = client.get_channel(config.CHANNEL_ID)
    if channel is None:
        logger.error("Channel %s not found - check CHANNEL_ID", config.CHANNEL_ID)
        return

    if first_run:
        logger.info("First run detected - scanning channel history for existing posts...")
        posted_urls = await scan_channel_history(channel)  # type: ignore[arg-type]

        # Mark items as seen if their URL is already in the channel
        items_to_post: list[ContentItem] = []
        for item in all_items:
            if item.url in posted_urls:
                seen.add(item.unique_id)
                logger.debug("Already posted: %s", item.url)
            else:
                items_to_post.append(item)

        save_seen(seen)

        if items_to_post:
            logger.info("Found %d items not yet posted - posting now", len(items_to_post))
            items_to_post.sort(key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc))
            for item in items_to_post:
                try:
                    embed = build_embed(item)
                    await channel.send(embed=embed)  # type: ignore[union-attr]
                    seen.add(item.unique_id)
                    save_seen(seen)
                    await asyncio.sleep(1)
                except discord.HTTPException:
                    logger.exception("Failed to send embed for %s", item.unique_id)
        else:
            logger.info("All %d items already posted in channel", len(all_items))
        return

    new_items = [item for item in all_items if item.unique_id not in seen]

    if not new_items:
        logger.info("No new content found")
        return

    # Sort by published date so oldest posts appear first
    new_items.sort(key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc))

    logger.info("Posting %d new item(s)", len(new_items))
    for item in new_items:
        try:
            embed = build_embed(item)
            await channel.send(embed=embed)  # type: ignore[union-attr]
            seen.add(item.unique_id)
            save_seen(seen)
            await asyncio.sleep(1)  # courtesy delay between sends
        except discord.HTTPException:
            logger.exception("Failed to send embed for %s", item.unique_id)
            # Don't mark as seen - will retry next cycle


@poll_sources.before_loop
async def before_poll() -> None:
    await client.wait_until_ready()


# ---------------------------------------------------------------------------
# Bot lifecycle
# ---------------------------------------------------------------------------

@client.event
async def on_ready() -> None:
    logger.info("Logged in as %s (ID: %s)", client.user, client.user.id if client.user else "?")
    logger.info("Poll interval: %d minutes", config.POLL_INTERVAL_MINUTES)
    logger.info("Target channel: %s", config.CHANNEL_ID)
    logger.info("Instagram enabled: %s", config.ENABLE_INSTAGRAM)

    if not poll_sources.is_running():
        poll_sources.start()


def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set - create a .env file (see .env.example)")
        return
    if config.CHANNEL_ID == 0:
        logger.error("CHANNEL_ID is not set - add it to your .env file")
        return

    client.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
