from __future__ import annotations

import pathlib

import pytest

from gamenews.franchises import ConfigError, load_franchises

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "franchises"


def test_valid_config_loads():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    assert {f.key for f in registry.franchises} == {"splatoon-3", "monster-hunter", "legend-of-zelda"}
    assert registry.media_events.default_platform == "nintendo"
    assert registry.media_events.legacy_newsroom_channel_id == 999999999999999999
    assert registry.media_events.channel_for_platform("nintendo") == 444444444444444444
    assert registry.media_events.channel_for_platform("playstation") == 555555555555555555


def test_missing_role_id_raises_named_error():
    # TC-8: a clear config error naming the offending franchise/field, not a silent None.
    with pytest.raises(ConfigError, match="splatoon-3.*role_id"):
        load_franchises(str(FIXTURES_DIR / "missing_role_id.yaml"))


def test_unknown_branding_key_raises():
    with pytest.raises(ConfigError, match="not-a-real-franchise"):
        load_franchises(str(FIXTURES_DIR / "unknown_branding_key.yaml"))


def test_persona_for_channel_uses_franchise_reporter():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    splatoon = registry.get("splatoon-3")
    name, avatar_path = registry.persona_for_channel(splatoon.channel_id)
    assert name == splatoon.reporter_name


def test_persona_for_unknown_channel_falls_back_to_default_platform():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    name, _ = registry.persona_for_channel(123)
    assert name == "Kosuke Takagi"


def test_reporter_name_defaults_to_display_name_when_omitted():
    # valid.yaml doesn't set reporter_name for any franchise.
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    splatoon = registry.get("splatoon-3")
    assert splatoon.reporter_name == splatoon.display_name


def test_unknown_platform_reference_raises():
    with pytest.raises(ConfigError, match="xbox"):
        load_franchises(str(FIXTURES_DIR / "unknown_platform_key.yaml"))


def test_persona_for_channel_uses_each_platform_channels_persona():
    # Feature: #nintendo-news and #playstation-news each post under their
    # own persona, chosen by channel.
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    media_events = registry.media_events

    nintendo_name, _ = registry.persona_for_channel(media_events.channel_for_platform("nintendo"))
    playstation_name, playstation_avatar = registry.persona_for_channel(
        media_events.channel_for_platform("playstation")
    )

    assert nintendo_name == "Kosuke Takagi"
    assert playstation_name == "Asuka Sato"
    assert playstation_avatar == "gamenews/assets/reporters/asuka_sato.png"


def test_unknown_default_platform_raises():
    with pytest.raises(ConfigError, match="default_platform"):
        load_franchises(str(FIXTURES_DIR / "unknown_default_platform.yaml"))


def test_platform_missing_channel_id_raises():
    with pytest.raises(ConfigError, match="nintendo.*channel_id"):
        load_franchises(str(FIXTURES_DIR / "platform_missing_channel_id.yaml"))


def test_role_for_platform_returns_configured_mute_role():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    assert registry.media_events.role_for_platform("playstation") == 255555555555555555


def test_role_for_platform_uses_default_platform_when_unset():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    assert registry.media_events.role_for_platform(None) == 244444444444444444
