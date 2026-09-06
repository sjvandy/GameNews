from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml


class ConfigError(Exception):
    """Raised for a franchises.yaml validation failure - always names the
    offending entry and field, per FR-1/TC-8 (no silent None, no guessing)."""


@dataclass
class FranchiseSource:
    type: str
    title_keywords: list[str] = field(default_factory=list)
    channel_id: str | None = None  # YouTube channel id (string, not a Discord snowflake)
    username: str | None = None  # Instagram username
    feeds: list[str] = field(default_factory=list)  # splatoon3ink feed names


@dataclass
class Franchise:
    key: str
    display_name: str
    channel_id: int
    role_id: int
    enable_ingame_events: bool
    event_keywords: list[str]
    sources: list[FranchiseSource]
    reporter_name: str
    reporter_avatar_path: str | None = None


@dataclass
class MediaEventsConfig:
    fallback_channel_id: int
    sources: list[FranchiseSource]
    franchise_branding_keywords: dict[str, list[str]]
    reporter_name: str = "GameNews"
    reporter_avatar_path: str | None = None

    def keywords(self) -> list[str]:
        result: list[str] = []
        for source in self.sources:
            result.extend(source.title_keywords)
        return result


@dataclass
class FranchiseRegistry:
    franchises: list[Franchise]
    media_events: MediaEventsConfig

    def get(self, key: str | None) -> Franchise | None:
        if key is None:
            return None
        for franchise in self.franchises:
            if franchise.key == key:
                return franchise
        return None

    def persona_for_channel(self, channel_id: int) -> tuple[str, str | None]:
        """The (reporter_name, reporter_avatar_path) that should post in this
        channel - a franchise's own persona if the channel belongs to one,
        otherwise the newsroom/fallback persona."""
        for franchise in self.franchises:
            if franchise.channel_id == channel_id:
                return franchise.reporter_name, franchise.reporter_avatar_path
        return self.media_events.reporter_name, self.media_events.reporter_avatar_path


_VALID_SOURCE_TYPES = {"youtube", "instagram", "news", "splatoon3ink"}


def _require(mapping: dict, field_name: str, context: str):
    if field_name not in mapping or mapping[field_name] in (None, ""):
        raise ConfigError(f"{context}: missing required field '{field_name}'")
    return mapping[field_name]


def _parse_source(raw: dict, context: str) -> FranchiseSource:
    source_type = _require(raw, "type", context)
    if source_type not in _VALID_SOURCE_TYPES:
        raise ConfigError(
            f"{context}: unknown source type '{source_type}' "
            f"(expected one of {sorted(_VALID_SOURCE_TYPES)})"
        )
    if source_type == "youtube":
        _require(raw, "channel_id", f"{context} (youtube source)")
    if source_type == "instagram":
        _require(raw, "username", f"{context} (instagram source)")

    return FranchiseSource(
        type=source_type,
        title_keywords=list(raw.get("title_keywords", [])),
        channel_id=raw.get("channel_id"),
        username=raw.get("username"),
        feeds=list(raw.get("feeds", [])),
    )


def _parse_franchise(raw: dict) -> Franchise:
    key = _require(raw, "key", "franchise entry")
    context = f"franchise '{key}'"
    display_name = _require(raw, "display_name", context)
    channel_id = int(_require(raw, "channel_id", context))
    role_id = int(_require(raw, "role_id", context))

    sources_raw = raw.get("sources") or []
    if not sources_raw:
        raise ConfigError(f"{context}: must define at least one source")
    sources = [_parse_source(s, f"{context} source") for s in sources_raw]

    return Franchise(
        key=key,
        display_name=display_name,
        channel_id=channel_id,
        role_id=role_id,
        enable_ingame_events=bool(raw.get("enable_ingame_events", False)),
        event_keywords=list(raw.get("event_keywords", [])),
        sources=sources,
        reporter_name=raw.get("reporter_name") or display_name,
        reporter_avatar_path=raw.get("reporter_avatar_path"),
    )


def _parse_media_events(raw: dict, franchise_keys: set[str]) -> MediaEventsConfig:
    context = "media_events"
    fallback_channel_id = int(_require(raw, "fallback_channel_id", context))

    sources_raw = raw.get("sources") or []
    sources = [_parse_source(s, f"{context} source") for s in sources_raw]

    branding = raw.get("franchise_branding_keywords", {}) or {}
    for franchise_key in branding:
        if franchise_key not in franchise_keys:
            raise ConfigError(
                f"{context}.franchise_branding_keywords references unknown "
                f"franchise '{franchise_key}'"
            )

    return MediaEventsConfig(
        fallback_channel_id=fallback_channel_id,
        sources=sources,
        franchise_branding_keywords={k: list(v) for k, v in branding.items()},
        reporter_name=raw.get("reporter_name") or "GameNews",
        reporter_avatar_path=raw.get("reporter_avatar_path"),
    )


def load_franchises(path: str) -> FranchiseRegistry:
    text = pathlib.Path(path).read_text()
    raw = yaml.safe_load(text) or {}

    franchises_raw = raw.get("franchises") or []
    if not franchises_raw:
        raise ConfigError(f"{path}: no franchises defined")

    franchises = [_parse_franchise(f) for f in franchises_raw]

    keys = [f.key for f in franchises]
    if len(keys) != len(set(keys)):
        raise ConfigError(f"{path}: duplicate franchise keys found")

    media_events_raw = raw.get("media_events") or {}
    media_events = _parse_media_events(media_events_raw, set(keys))

    return FranchiseRegistry(franchises=franchises, media_events=media_events)
