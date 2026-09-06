from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from gamenews.events.builder import EventCandidate
from gamenews.franchises import Franchise

logger = logging.getLogger(__name__)

SCHEDULES_URL = "https://splatoon3.ink/data/schedules.json"
FESTIVALS_URL = "https://splatoon3.ink/data/festivals.json"
FESTIVALS_REGION = "US"

# Data refreshes hourly upstream and splatoon3.ink asks integrations not to
# poll more than once/hour; SplatoonScheduleCog's loop interval enforces that.
# Attribution ("Schedule data via splatoon3.ink") is embedded in each event's
# description per their usage terms.
USER_AGENT = "GameNewsDiscordBot/1.0 (personal Discord bot; https://github.com/)"


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
        resp.raise_for_status()
        return await resp.json()


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _coop_event_candidates(schedules: dict, franchise: Franchise) -> list[EventCandidate]:
    grouping = schedules.get("data", {}).get("coopGroupingSchedule", {})
    candidates: list[EventCandidate] = []

    for kind, label, node_key in (
        ("bigrun", "Big Run", "bigRunSchedules"),
        ("eggstrawork", "Eggstra Work", "teamContestSchedules"),
    ):
        for node in grouping.get(node_key, {}).get("nodes", []):
            setting = node.get("setting", {})
            coop_stage = setting.get("coopStage", {})
            stage_name = coop_stage.get("name", "Salmon Run")
            start = _parse_time(node["startTime"])
            end = _parse_time(node["endTime"])

            candidates.append(
                EventCandidate(
                    event_type="ingame",
                    franchise_key=franchise.key,
                    branded_franchise_key=None,
                    source_unique_id=f"splatoon3ink:{kind}:{node['startTime']}",
                    name=f"Splatoon 3: {label} — {stage_name}",
                    description=f"{label} Salmon Run event. Schedule data via splatoon3.ink.",
                    start_time=start,
                    end_time=end,
                    location=f"{franchise.display_name} — Online",
                    cover_image_url=coop_stage.get("thumbnailImage", {}).get("url"),
                )
            )

    return candidates


def _festival_candidates(festivals: dict, franchise: Franchise) -> list[EventCandidate]:
    region_data = festivals.get(FESTIVALS_REGION, {})
    nodes = region_data.get("data", {}).get("festRecords", {}).get("nodes", [])
    now = datetime.now(timezone.utc)
    candidates: list[EventCandidate] = []

    for node in nodes:
        end = _parse_time(node["endTime"])
        if end < now:
            continue  # historical - nothing to schedule

        start = _parse_time(node["startTime"])
        title = node.get("title", "Splatfest")
        node_id = node.get("id", node["startTime"])

        candidates.append(
            EventCandidate(
                event_type="ingame",
                franchise_key=franchise.key,
                branded_franchise_key=None,
                source_unique_id=f"splatoon3ink:splatfest:{node_id}",
                name=f"Splatoon 3 Splatfest: {title}",
                description="Splatfest event. Schedule data via splatoon3.ink.",
                start_time=start,
                end_time=end,
                location=f"{franchise.display_name} — Online",
                cover_image_url=node.get("image", {}).get("url"),
            )
        )

    return candidates


async def fetch_schedule(franchise: Franchise) -> list[EventCandidate]:
    """Structured Splatoon 3 in-game event data (Big Run, Eggstra Work,
    Splatfests) from the splatoon3.ink community API - exact start/end
    timestamps, so unlike keyword-scraped sources, these never hit the
    "unparseable date, skip" path (SRS FR-4/TC-4).
    """
    try:
        async with aiohttp.ClientSession() as session:
            schedules = await _get_json(session, SCHEDULES_URL)
            festivals = await _get_json(session, FESTIVALS_URL)
    except Exception:
        logger.exception("splatoon3.ink: fetch failed")
        return []

    candidates: list[EventCandidate] = []
    candidates.extend(_coop_event_candidates(schedules, franchise))
    candidates.extend(_festival_candidates(festivals, franchise))
    logger.info("splatoon3.ink: found %d event candidate(s)", len(candidates))
    return candidates
