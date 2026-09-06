"""SRS 9.2 fixture-based regression suite.

Each *.item.json in tests/fixtures/replay/ is a real-world content item
(a curated Splatfest announcement, Monster Hunter event, Nintendo Direct,
branded Zelda Direct, and an unparseable-date case). Its *.expected.json
sibling was generated once by actually running run_replay_from_item and
reviewing the output (see the SRS's own instructions), then committed as
the reference. This test only re-runs the pure, offline replay pipeline
against those committed snapshots - no live network calls, so it's safe
and deterministic in CI.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest

from gamenews.franchises import load_franchises
from gamenews.tools.replay import _to_jsonable, run_replay_from_item
from tests.conftest import load_item_fixture

REPLAY_DIR = pathlib.Path(__file__).parent / "fixtures" / "replay"
REGISTRY = load_franchises(str(pathlib.Path(__file__).parent / "fixtures" / "franchises" / "valid.yaml"))

# Fixtures embed real calendar dates (e.g. "9.4.2026"). Date extraction now
# rejects any date that's already passed relative to "now" (see
# events/dates.py), so without pinning a fixed reference here, these
# fixtures would silently start failing once real time passes the dates
# they contain - pin it well before every date used in fixtures/replay/.
REFERENCE = datetime(2026, 9, 1, tzinfo=timezone.utc)

FIXTURE_NAMES = sorted(p.stem.removesuffix(".item") for p in REPLAY_DIR.glob("*.item.json"))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_replay_matches_committed_snapshot(name: str):
    item = load_item_fixture(REPLAY_DIR / f"{name}.item.json")
    expected = json.loads((REPLAY_DIR / f"{name}.expected.json").read_text())

    result = run_replay_from_item(item, REGISTRY, reference=REFERENCE)

    assert _to_jsonable(result) == expected
