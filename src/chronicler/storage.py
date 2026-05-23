"""SQLite storage layer.

Two tables:
- events: one row per ChronicleEvent (JSON-serialized payload + key columns for query)
- chronicles: one row per (event_id, agent) — the LLM-generated narrative

Re-importing the same save is idempotent: event_id is the primary key for
events, and (event_id, agent) is unique in chronicles.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .schema import ChronicleEvent, EventType


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    type         TEXT NOT NULL,
    year         INTEGER NOT NULL,
    primary_actor_id   TEXT,
    primary_actor_name TEXT,
    payload      TEXT NOT NULL,  -- full JSON
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_year ON events(year);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_primary_actor ON events(primary_actor_id);

CREATE TABLE IF NOT EXISTS chronicles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    agent        TEXT NOT NULL,
    title        TEXT,
    body         TEXT NOT NULL,
    model        TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_input_tokens INTEGER,
    cost_usd     REAL,
    created_at   TEXT NOT NULL,
    UNIQUE(event_id, agent),
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_chronicles_agent ON chronicles(agent);

CREATE TABLE IF NOT EXISTS import_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path  TEXT NOT NULL,
    event_count  INTEGER NOT NULL,
    imported_at  TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA_SQL)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- events ----

    def upsert_event(self, event: ChronicleEvent) -> bool:
        """Returns True if inserted, False if already existed."""
        payload = event.model_dump_json()
        primary = event.primary_actors[0]
        with self._conn() as c:
            cur = c.execute(
                "SELECT 1 FROM events WHERE event_id = ?", (event.event_id,)
            )
            if cur.fetchone():
                return False
            c.execute(
                """
                INSERT INTO events (
                    event_id, source, type, year,
                    primary_actor_id, primary_actor_name,
                    payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.source.value,
                    event.type.value,
                    event.year,
                    primary.character_id,
                    primary.name,
                    payload,
                    _now(),
                ),
            )
            return True

    def upsert_events(self, events: Iterable[ChronicleEvent]) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        for ev in events:
            if self.upsert_event(ev):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped

    def get_event(self, event_id: str) -> Optional[ChronicleEvent]:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if not row:
            return None
        return ChronicleEvent.model_validate_json(row["payload"])

    def list_events(
        self,
        *,
        from_year: Optional[int] = None,
        to_year: Optional[int] = None,
        event_type: Optional[EventType] = None,
        character_id: Optional[str] = None,
    ) -> list[ChronicleEvent]:
        sql = "SELECT payload FROM events WHERE 1=1"
        params: list = []
        if from_year is not None:
            sql += " AND year >= ?"
            params.append(from_year)
        if to_year is not None:
            sql += " AND year <= ?"
            params.append(to_year)
        if event_type is not None:
            sql += " AND type = ?"
            params.append(event_type.value)
        if character_id is not None:
            sql += " AND primary_actor_id = ?"
            params.append(character_id)
        sql += " ORDER BY year ASC, event_id ASC"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [ChronicleEvent.model_validate_json(r["payload"]) for r in rows]

    # ---- chronicles ----

    def has_chronicle(self, event_id: str, agent: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM chronicles WHERE event_id = ? AND agent = ?",
                (event_id, agent),
            ).fetchone()
        return row is not None

    def save_chronicle(
        self,
        *,
        event_id: str,
        agent: str,
        title: Optional[str],
        body: str,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cached_input_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO chronicles (
                    event_id, agent, title, body, model,
                    input_tokens, output_tokens, cached_input_tokens,
                    cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, agent) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    model = excluded.model,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    cached_input_tokens = excluded.cached_input_tokens,
                    cost_usd = excluded.cost_usd,
                    created_at = excluded.created_at
                """,
                (
                    event_id,
                    agent,
                    title,
                    body,
                    model,
                    input_tokens,
                    output_tokens,
                    cached_input_tokens,
                    cost_usd,
                    _now(),
                ),
            )

    def list_chronicles_for_event(self, event_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT agent, title, body, model FROM chronicles WHERE event_id = ?",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def total_cost(self) -> float:
        with self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) AS total FROM chronicles"
            ).fetchone()
        return float(row["total"])

    def log_import(self, source_path: str, event_count: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO import_log (source_path, event_count, imported_at) VALUES (?, ?, ?)",
                (source_path, event_count, _now()),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
