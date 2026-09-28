from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from gamenews.cogs.notifications import NotificationsCog


def _mock_ctx(*, guild=None, author=None):
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.send = AsyncMock()
    return ctx


def _mock_member(*, roles=None):
    member = MagicMock(spec=discord.Member)
    member.roles = roles or []
    member.id = 42
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


@pytest.fixture
def cog(registry):
    bot = MagicMock()
    bot.franchises = registry
    instance = NotificationsCog.__new__(NotificationsCog)
    instance.bot = bot
    return instance


@pytest.mark.asyncio
async def test_mute_removes_platform_role_when_present(cog, registry):
    role = MagicMock(spec=discord.Role)
    role.id = registry.media_events.role_for_platform("playstation")
    member = _mock_member(roles=[role])
    guild = MagicMock(spec=discord.Guild)
    guild.get_role = MagicMock(return_value=role)
    ctx = _mock_ctx(guild=guild, author=member)

    await cog._toggle(ctx, "playstation", mute=True)

    member.remove_roles.assert_awaited_once_with(role, reason="Self-muted via /mute")


@pytest.mark.asyncio
async def test_unmute_adds_platform_role_when_absent(cog, registry):
    role = MagicMock(spec=discord.Role)
    role.id = registry.media_events.role_for_platform("nintendo")
    member = _mock_member(roles=[])
    guild = MagicMock(spec=discord.Guild)
    guild.get_role = MagicMock(return_value=role)
    ctx = _mock_ctx(guild=guild, author=member)

    await cog._toggle(ctx, "nintendo", mute=False)

    member.add_roles.assert_awaited_once_with(role, reason="Self-unmuted via /unmute")


@pytest.mark.asyncio
async def test_mute_already_muted_is_a_noop(cog, registry):
    role = MagicMock(spec=discord.Role)
    role.id = registry.media_events.role_for_platform("playstation")
    member = _mock_member(roles=[])  # doesn't have the role already
    guild = MagicMock(spec=discord.Guild)
    guild.get_role = MagicMock(return_value=role)
    ctx = _mock_ctx(guild=guild, author=member)

    await cog._toggle(ctx, "playstation", mute=True)

    member.remove_roles.assert_not_called()
    ctx.send.assert_awaited_once()
    assert "already" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_unknown_platform_reports_available_choices(cog):
    guild = MagicMock(spec=discord.Guild)
    ctx = _mock_ctx(guild=guild, author=_mock_member())

    await cog._toggle(ctx, "xbox", mute=True)

    ctx.send.assert_awaited_once()
    assert "Unknown platform" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_platform_without_configured_role_reports_setup_needed(cog):
    # valid.yaml's fixture has both platforms configured with a role_id, so
    # exercise a registry where one legitimately isn't set up yet.
    cog.bot.franchises.media_events.platforms["nintendo"].role_id = None
    guild = MagicMock(spec=discord.Guild)
    ctx = _mock_ctx(guild=guild, author=_mock_member())

    await cog._toggle(ctx, "nintendo", mute=True)

    ctx.send.assert_awaited_once()
    assert "No ping role is configured" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_toggle_in_dms_is_rejected(cog):
    ctx = _mock_ctx(guild=None, author=_mock_member())

    await cog._toggle(ctx, "playstation", mute=True)

    ctx.send.assert_awaited_once()
    assert "DMs" in ctx.send.call_args.args[0]
