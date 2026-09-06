from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS content_postings (
    unique_id  TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    source     TEXT NOT NULL,
    posted_at  TEXT NOT NULL,
    PRIMARY KEY (unique_id, channel_id)
);

CREATE TABLE IF NOT EXISTS tracked_events (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_scheduled_event_id  TEXT UNIQUE,
    event_type                TEXT NOT NULL CHECK(event_type IN ('ingame','media')),
    franchise_key             TEXT,
    branded_franchise_key     TEXT,
    source_unique_id          TEXT,
    name        TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'SCHEDULED' CHECK(status IN ('SCHEDULED','ACTIVE','COMPLETED','CANCELED')),
    role_pinged_at TEXT,
    announced_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_events_source
    ON tracked_events(source_unique_id) WHERE source_unique_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tracked_events_status ON tracked_events(status);
"""

# Forward-only migrations for databases created before a schema change.
# CREATE TABLE IF NOT EXISTS above already gives fresh installs the current
# shape; this only patches existing on-disk databases. Tracked via
# PRAGMA user_version so each migration runs at most once.
MIGRATIONS: list[str] = [
    "ALTER TABLE tracked_events ADD COLUMN announced_at TEXT",
]


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class Database:
    """Thin async wrapper around a single sqlite3 connection.

    Call volume is low (one content poll per ~15 min, one event tick per
    1-5 min), so blocking calls are pushed to a thread via asyncio.to_thread
    rather than pulling in aiosqlite; a lock serializes access since the
    single shared connection isn't safe for concurrent use across threads.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self, legacy_seen_posts_path: str = "", legacy_fallback_channel_id: int = 0) -> None:
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        def _setup() -> None:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for migration in MIGRATIONS[version:]:
                try:
                    self._conn.execute(migration)
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc).lower():
                        raise
            self._conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
            self._conn.commit()

        await asyncio.to_thread(_setup)

        if legacy_seen_posts_path and legacy_fallback_channel_id:
            await self._import_legacy_seen_posts(legacy_seen_posts_path, legacy_fallback_channel_id)

    async def _import_legacy_seen_posts(self, legacy_path: str, fallback_channel_id: int) -> None:
        def _count() -> int:
            cur = self._conn.execute("SELECT COUNT(*) FROM content_postings")
            return cur.fetchone()[0]

        existing = await asyncio.to_thread(_count)
        if existing > 0:
            return

        legacy_file = pathlib.Path(legacy_path)
        if not legacy_file.exists():
            return

        try:
            ids = json.loads(legacy_file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read legacy %s - skipping import", legacy_path)
            return

        if not isinstance(ids, list) or not ids:
            return

        now = _iso(datetime.now(timezone.utc))

        def _insert() -> None:
            for unique_id in ids:
                source = unique_id.split(":", 1)[0] if ":" in unique_id else "unknown"
                self._conn.execute(
                    "INSERT OR IGNORE INTO content_postings (unique_id, channel_id, source, posted_at) "
                    "VALUES (?, ?, ?, ?)",
                    (unique_id, fallback_channel_id, source, now),
                )
            self._conn.commit()

        await asyncio.to_thread(_insert)
        logger.info("Imported %d legacy seen-post ids from %s", len(ids), legacy_path)

    async def is_posted(self, unique_id: str, channel_id: int) -> bool:
        def _query() -> bool:
            cur = self._conn.execute(
                "SELECT 1 FROM content_postings WHERE unique_id = ? AND channel_id = ?",
                (unique_id, channel_id),
            )
            return cur.fetchone() is not None

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def has_any_posting(self, channel_id: int) -> bool:
        def _query() -> bool:
            cur = self._conn.execute(
                "SELECT 1 FROM content_postings WHERE channel_id = ? LIMIT 1", (channel_id,)
            )
            return cur.fetchone() is not None

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def mark_posted(self, unique_id: str, channel_id: int, source: str) -> None:
        now = _iso(datetime.now(timezone.utc))

        def _insert() -> None:
            self._conn.execute(
                "INSERT OR IGNORE INTO content_postings (unique_id, channel_id, source, posted_at) "
                "VALUES (?, ?, ?, ?)",
                (unique_id, channel_id, source, now),
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_insert)

    async def get_tracked_event_by_source(self, source_unique_id: str) -> sqlite3.Row | None:
        def _query() -> sqlite3.Row | None:
            cur = self._conn.execute(
                "SELECT * FROM tracked_events WHERE source_unique_id = ?", (source_unique_id,)
            )
            return cur.fetchone()

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def insert_tracked_event(
        self,
        *,
        guild_scheduled_event_id: str,
        event_type: str,
        franchise_key: str | None,
        branded_franchise_key: str | None,
        source_unique_id: str,
        name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        def _insert() -> int:
            cur = self._conn.execute(
                """
                INSERT INTO tracked_events (
                    guild_scheduled_event_id, event_type, franchise_key,
                    branded_franchise_key, source_unique_id, name, start_time, end_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_scheduled_event_id,
                    event_type,
                    franchise_key,
                    branded_franchise_key,
                    source_unique_id,
                    name,
                    _iso(start_time),
                    _iso(end_time),
                ),
            )
            self._conn.commit()
            return cur.lastrowid

        async with self._lock:
            return await asyncio.to_thread(_insert)

    async def get_scheduled_tracked_events(self) -> list[sqlite3.Row]:
        """Every tracked event still SCHEDULED (not yet started/completed/
        cancelled) - the refresh candidates for /refresh."""

        def _query() -> list[sqlite3.Row]:
            cur = self._conn.execute("SELECT * FROM tracked_events WHERE status = 'SCHEDULED'")
            return cur.fetchall()

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def update_event_fields(
        self, row_id: int, *, name: str, start_time: datetime, end_time: datetime
    ) -> None:
        def _update() -> None:
            self._conn.execute(
                "UPDATE tracked_events SET name = ?, start_time = ?, end_time = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (name, _iso(start_time), _iso(end_time), row_id),
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    async def get_due_scheduled_events(self, now: datetime) -> list[sqlite3.Row]:
        def _query() -> list[sqlite3.Row]:
            cur = self._conn.execute(
                "SELECT * FROM tracked_events "
                "WHERE status IN ('SCHEDULED', 'ACTIVE') AND start_time <= ?",
                (_iso(now),),
            )
            return cur.fetchall()

        async with self._lock:
            return await asyncio.to_thread(_query)

    async def update_event_status(self, row_id: int, status: str) -> None:
        def _update() -> None:
            self._conn.execute(
                "UPDATE tracked_events SET status = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (status, row_id),
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    async def mark_role_pinged(self, row_id: int) -> None:
        now = _iso(datetime.now(timezone.utc))

        def _update() -> None:
            self._conn.execute(
                "UPDATE tracked_events SET role_pinged_at = ? WHERE id = ?", (now, row_id)
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    async def mark_announced(self, row_id: int) -> None:
        now = _iso(datetime.now(timezone.utc))

        def _update() -> None:
            self._conn.execute(
                "UPDATE tracked_events SET announced_at = ? WHERE id = ?", (now, row_id)
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
