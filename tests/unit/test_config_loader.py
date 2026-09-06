from __future__ import annotations

import pathlib

import pytest

from gamenews.franchises import ConfigError, load_franchises

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "franchises"


def test_valid_config_loads():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    assert {f.key for f in registry.franchises} == {"splatoon-3", "monster-hunter", "legend-of-zelda"}
    assert registry.media_events.fallback_channel_id == 999999999999999999


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


def test_persona_for_channel_falls_back_to_newsroom_reporter():
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    name, avatar_path = registry.persona_for_channel(registry.media_events.fallback_channel_id)
    assert name == registry.media_events.reporter_name


def test_reporter_name_defaults_to_display_name_when_omitted():
    # valid.yaml doesn't set reporter_name for any franchise.
    registry = load_franchises(str(FIXTURES_DIR / "valid.yaml"))
    splatoon = registry.get("splatoon-3")
    assert splatoon.reporter_name == splatoon.display_name
