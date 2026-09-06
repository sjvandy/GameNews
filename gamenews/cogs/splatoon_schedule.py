from __future__ import annotations

import logging

from discord.ext import commands, tasks

from gamenews import config
from gamenews.sources import splatoon3ink

logger = logging.getLogger(__name__)

SPLATOON_FRANCHISE_KEY = "splatoon-3"


class SplatoonScheduleCog(commands.Cog):
    """Feeds splatoon3.ink's structured rotation/Splatfest data straight into
    EventLifecycleManager, bypassing the keyword/date-guessing pipeline
    entirely for Splatoon in-game events. Hourly interval matches
    splatoon3.ink's own refresh cadence and rate-limit terms."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.poll_splatoon_schedule.start()

    def cog_unload(self) -> None:
        self.poll_splatoon_schedule.cancel()

    @tasks.loop(hours=1)
    async def poll_splatoon_schedule(self) -> None:
        franchise = self.bot.franchises.get(SPLATOON_FRANCHISE_KEY)
        if franchise is None or not franchise.enable_ingame_events:
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            logger.error("Guild %s not found - check GUILD_ID", config.GUILD_ID)
            return

        candidates = await splatoon3ink.fetch_schedule(franchise)
        for candidate in candidates:
            await self.bot.event_manager.create_event(guild, candidate)

    @poll_splatoon_schedule.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SplatoonScheduleCog(bot))
