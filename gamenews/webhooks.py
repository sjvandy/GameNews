from __future__ import annotations

import logging
import pathlib

import discord

logger = logging.getLogger(__name__)


class WebhookManager:
    """Gives each franchise/newsroom channel its own persistent posting
    identity (a name + avatar, e.g. "Shiver" for Splatoon) via a per-channel
    Discord webhook, rather than every message coming from the bot's own
    generic identity. Requires the Manage Webhooks permission.

    A webhook - not the bot user - is what's renamed/re-skinned here, so
    this has no effect on the bot's own Discord Developer Portal identity.
    """

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self._cache: dict[int, discord.Webhook] = {}

    async def get(self, channel_id: int, name: str, avatar_path: str | None) -> discord.Webhook | None:
        cached = self._cache.get(channel_id)
        if cached is not None:
            return cached

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.error("Cannot set up reporter webhook - channel %s not found", channel_id)
            return None

        avatar_bytes = self._read_avatar(avatar_path)

        try:
            existing = await channel.webhooks()
        except discord.Forbidden:
            logger.error(
                "Missing Manage Webhooks permission in channel %s - falling back to the bot's own identity",
                channel_id,
            )
            return None
        except discord.HTTPException:
            logger.exception("Failed to list webhooks for channel %s", channel_id)
            return None

        webhook = next(
            (w for w in existing if w.user and self.bot.user and w.user.id == self.bot.user.id), None
        )

        try:
            if webhook is None:
                webhook = await channel.create_webhook(
                    name=name, avatar=avatar_bytes, reason="GameNews per-channel reporter persona"
                )
                logger.info("Created reporter webhook '%s' in channel %s", name, channel_id)
            elif webhook.name != name or avatar_bytes is not None:
                await webhook.edit(name=name, avatar=avatar_bytes)
        except discord.HTTPException:
            logger.exception("Failed to create/update reporter webhook for channel %s", channel_id)
            return None

        self._cache[channel_id] = webhook
        return webhook

    @staticmethod
    def _read_avatar(avatar_path: str | None) -> bytes | None:
        if not avatar_path:
            return None
        path = pathlib.Path(avatar_path)
        if not path.exists():
            logger.info(
                "Reporter avatar not found at %s yet - using Discord's default icon for now", avatar_path
            )
            return None
        return path.read_bytes()
