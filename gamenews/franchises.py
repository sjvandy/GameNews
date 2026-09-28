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
    platform: str | None = None  # media_events source only: which PlatformPersona this feeds
    # media_events youtube source only: any video from this channel with the
    # standalone word "Direct" is a Direct, even without a title_keywords hit.
    match_direct_word: bool = False


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
class PlatformPersona:
    """One platform's own newsroom channel (e.g. #nintendo-news vs
    #playstation-news): the reporter identity that posts there and the
    opt-in role its Directs/State of Plays ping."""

    key: str
    channel_id: int
    reporter_name: str
    reporter_avatar_path: str | None = None
    role_id: int | None = None  # opt-in: only members who /unmute this platform get pinged


@dataclass
class MediaEventsConfig:
    sources: list[FranchiseSource]
    franchise_branding_keywords: dict[str, list[str]]
    platforms: dict[str, PlatformPersona]
    default_platform: str  # where untagged content goes
    # The retired shared #newsroom channel, kept only so the legacy
    # seen_posts import and first-run seeding of the new platform channels
    # know what was already posted there.
    legacy_newsroom_channel_id: int | None = None

    def keywords(self) -> list[str]:
        result: list[str] = []
        for source in self.sources:
            result.extend(source.title_keywords)
        return result

    def direct_word_channel_ids(self) -> set[str]:
        return {
            s.channel_id
            for s in self.sources
            if s.type == "youtube" and s.match_direct_word and s.channel_id
        }

    def platform_for(self, platform: str | None) -> PlatformPersona:
        """`platform`'s persona, or the default platform's when `platform`
        is unset or unknown."""
        return self.platforms.get(platform or "") or self.platforms[self.default_platform]

    def channel_for_platform(self, platform: str | None) -> int:
        return self.platform_for(platform).channel_id

    def persona_for_platform(self, platform: str | None) -> tuple[str, str | None]:
        persona = self.platform_for(platform)
        return persona.reporter_name, persona.reporter_avatar_path

    def role_for_platform(self, platform: str | None) -> int | None:
        """The opt-in role to ping for `platform`'s Directs/State of Plays,
        or None if that platform has no role configured (nobody is pinged)."""
        return self.platform_for(platform).role_id

    def platform_channel_ids(self) -> list[int]:
        return [persona.channel_id for persona in self.platforms.values()]


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
        otherwise that platform channel's persona (e.g. Nintendo vs
        PlayStation), falling back to the default platform's."""
        for franchise in self.franchises:
            if franchise.channel_id == channel_id:
                return franchise.reporter_name, franchise.reporter_avatar_path
        for persona in self.media_events.platforms.values():
            if persona.channel_id == channel_id:
                return persona.reporter_name, persona.reporter_avatar_path
        return self.media_events.persona_for_platform(None)


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
        platform=raw.get("platform"),
        match_direct_word=bool(raw.get("match_direct_word", False)),
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


def _parse_platform_persona(key: str, raw: dict, context: str) -> PlatformPersona:
    channel_id = int(_require(raw, "channel_id", context))
    reporter_name = _require(raw, "reporter_name", context)
    role_id_raw = raw.get("role_id")
    return PlatformPersona(
        key=key,
        channel_id=channel_id,
        reporter_name=reporter_name,
        reporter_avatar_path=raw.get("reporter_avatar_path"),
        role_id=int(role_id_raw) if role_id_raw not in (None, "") else None,
    )


def _parse_media_events(raw: dict, franchise_keys: set[str]) -> MediaEventsConfig:
    context = "media_events"

    sources_raw = raw.get("sources") or []
    sources = [_parse_source(s, f"{context} source") for s in sources_raw]

    branding = raw.get("franchise_branding_keywords", {}) or {}
    for franchise_key in branding:
        if franchise_key not in franchise_keys:
            raise ConfigError(
                f"{context}.franchise_branding_keywords references unknown "
                f"franchise '{franchise_key}'"
            )

    platforms_raw = raw.get("platforms") or {}
    platforms = {
        key: _parse_platform_persona(key, p, f"{context}.platforms.'{key}'")
        for key, p in platforms_raw.items()
    }

    for source in sources:
        if source.platform and source.platform not in platforms:
            raise ConfigError(
                f"{context} source references unknown platform '{source.platform}' "
                f"(expected one of {sorted(platforms)})"
            )

    if not platforms:
        raise ConfigError(f"{context}: must define at least one platform under 'platforms'")

    default_platform = _require(raw, "default_platform", context)
    if default_platform not in platforms:
        raise ConfigError(
            f"{context}.default_platform '{default_platform}' is not a configured "
            f"platform (expected one of {sorted(platforms)})"
        )

    channel_ids = [p.channel_id for p in platforms.values()]
    if len(channel_ids) != len(set(channel_ids)):
        raise ConfigError(f"{context}.platforms: each platform needs its own channel_id")

    legacy_raw = raw.get("legacy_newsroom_channel_id")
    return MediaEventsConfig(
        sources=sources,
        franchise_branding_keywords={k: list(v) for k, v in branding.items()},
        platforms=platforms,
        default_platform=default_platform,
        legacy_newsroom_channel_id=int(legacy_raw) if legacy_raw not in (None, "") else None,
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
