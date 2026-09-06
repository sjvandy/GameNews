from __future__ import annotations

import logging

import discord
from discord.ext import commands

from gamenews import config
from gamenews.db import Database
from gamenews.events.lifecycle import EventLifecycleManager
from gamenews.franchises import ConfigError, FranchiseRegistry, load_franchises
from gamenews.webhooks import WebhookManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gamenews")

INITIAL_COGS = (
    "gamenews.cogs.content_poll",
    "gamenews.cogs.event_scheduler",
    "gamenews.cogs.splatoon_schedule",
    "gamenews.cogs.admin",
)


class GameNewsBot(commands.Bot):
    def __init__(self, franchises: FranchiseRegistry) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read embed URLs from channel history
        super().__init__(command_prefix="!gamenews ", intents=intents)
        self.franchises = franchises

    async def setup_hook(self) -> None:
        self.db = Database(config.DB_PATH)
        await self.db.init(
            legacy_seen_posts_path=config.LEGACY_SEEN_POSTS_PATH,
            legacy_fallback_channel_id=self.franchises.media_events.fallback_channel_id,
        )

        self.webhooks = WebhookManager(self)
        self.event_manager = EventLifecycleManager(self, self.db, self.franchises)

        for cog in INITIAL_COGS:
            await self.load_extension(cog)

        # Guild-scoped sync propagates instantly (a global sync can take up
        # to an hour to show up), which matters for a single-server bot
        # whose slash commands (e.g. /cleanup, /duplicates) you want
        # available right after a restart, not sometime later.
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info("Synced %d slash command(s) to guild %s", len(synced), config.GUILD_ID)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        logger.info("Guild: %s", config.GUILD_ID)
        logger.info("Franchises loaded: %s", ", ".join(f.key for f in self.franchises.franchises))

    async def close(self) -> None:
        if hasattr(self, "db"):
            self.db.close()
        await super().close()


def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set - create a .env file (see .env.example)")
        return
    if config.GUILD_ID == 0:
        logger.error("GUILD_ID is not set - add it to your .env file")
        return

    # Validated before the bot ever connects, so a bad franchises.yaml fails
    # loudly at startup (TC-8) rather than surfacing later as a silent no-op.
    try:
        franchises = load_franchises(config.FRANCHISES_CONFIG_PATH)
    except ConfigError as exc:
        logger.error("franchises.yaml config error: %s", exc)
        return

    bot = GameNewsBot(franchises)
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
