from __future__ import annotations

import logging

from discord.ext import commands, tasks

from gamenews import config

logger = logging.getLogger(__name__)


class EventSchedulerCog(commands.Cog):
    """FR-6: a fine-grained tick (independent of the 15-min content poll) that
    flips SCHEDULED events to ACTIVE at their start time and pings roles
    (FR-7). Discord never auto-activates events and will auto-cancel one left
    SCHEDULED too long past its start time, so this loop must run often
    enough to beat that."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_events.change_interval(minutes=config.EVENT_CHECK_INTERVAL_MINUTES)
        self.check_events.start()

    def cog_unload(self) -> None:
        self.check_events.cancel()

    @tasks.loop(minutes=2)
    async def check_events(self) -> None:
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            logger.error("Guild %s not found - check GUILD_ID", config.GUILD_ID)
            return
        await self.bot.event_manager.maybe_start_due_events(guild)

    @check_events.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventSchedulerCog(bot))
