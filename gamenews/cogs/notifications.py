from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class NotificationsCog(commands.Cog):
    """Opt-in pings for each platform's news channel (#nintendo-news,
    #playstation-news). Those channels are muted by default: their event
    announcements/go-live pings only mention that platform's role, which
    starts empty, so members /unmute a platform to join the role and start
    getting pinged, and /mute it to leave again.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _platform_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current = current.lower()
        return [
            app_commands.Choice(name=persona.reporter_name, value=key)
            for key, persona in self.bot.franchises.media_events.platforms.items()
            if current in key.lower()
        ][:25]

    async def _toggle(self, ctx: commands.Context, platform: str, *, mute: bool) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await ctx.send("This only works in the server, not in DMs.")
            return

        persona = self.bot.franchises.media_events.platforms.get(platform.lower())
        if persona is None:
            available = ", ".join(self.bot.franchises.media_events.platforms) or "none configured"
            await ctx.send(f"Unknown platform `{platform}`. Available: {available}")
            return

        if persona.role_id is None:
            await ctx.send(
                f"No ping role is configured for <#{persona.channel_id}> yet - "
                "add a `role_id` under that platform in `franchises.yaml`."
            )
            return

        role = ctx.guild.get_role(persona.role_id)
        if role is None:
            await ctx.send(
                f"The role configured for <#{persona.channel_id}> "
                f"(`{persona.role_id}`) no longer exists on this server."
            )
            return

        already = role in ctx.author.roles
        if mute and not already:
            await ctx.send(f"<#{persona.channel_id}> is already muted for you (it's muted by default).")
            return
        if not mute and already:
            await ctx.send(f"You're already getting pinged for <#{persona.channel_id}>.")
            return

        try:
            if mute:
                await ctx.author.remove_roles(role, reason="Self-muted via /mute")
                await ctx.send(
                    f"Muted <#{persona.channel_id}>. "
                    f"Run `/unmute platform:{persona.key}` to turn pings back on."
                )
            else:
                await ctx.author.add_roles(role, reason="Self-unmuted via /unmute")
                await ctx.send(
                    f"Unmuted <#{persona.channel_id}> - you'll now get pinged for "
                    f"**{persona.reporter_name}**'s event announcements."
                )
        except discord.Forbidden:
            await ctx.send(
                "I don't have permission to manage that role - check that I have "
                "**Manage Roles** and that my own role sits above it in Server Settings > Roles."
            )
        except discord.HTTPException:
            logger.exception("Failed to toggle role %s for member %s", role.id, ctx.author.id)
            await ctx.send("Something went wrong changing that role - see the logs.")

    @commands.hybrid_command(name="mute")
    @app_commands.describe(platform="Which platform's news channel to stop getting pinged for")
    @app_commands.autocomplete(platform=_platform_autocomplete)
    async def mute(self, ctx: commands.Context, platform: str) -> None:
        """Stop getting pinged in one platform's news channel (the default)."""
        await self._toggle(ctx, platform, mute=True)

    @commands.hybrid_command(name="unmute")
    @app_commands.describe(platform="Which platform's news channel to start getting pinged for")
    @app_commands.autocomplete(platform=_platform_autocomplete)
    async def unmute(self, ctx: commands.Context, platform: str) -> None:
        """Opt in to pings for one platform's news channel (Directs/State of Plays)."""
        await self._toggle(ctx, platform, mute=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotificationsCog(bot))
