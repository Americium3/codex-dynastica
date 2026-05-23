"""SQLite storage layer.

Tables:
- events: one row per ChronicleEvent (JSON-serialized payload + key columns)
- chronicles: one row per (event_id, agent, language) — the LLM-generated narrative
- import_log: provenance of save/jsonl imports

Idempotent: event_id is the PK of events; (event_id, agent, language) is
the unique index on chronicles, so re-running import or generate never
duplicates.

Migration: if an old (Phase 0 pre-i18n) chronicles table exists without
the `language` column, we transparently ALTER it and stamp existing rows
as 'en'.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .schema import ChronicleEvent, EventType

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    type         TEXT NOT NULL,
    year         INTEGER NOT NULL,
    primary_actor_id   TEXT,
    primary_actor_name TEXT,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_year ON events(year);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_primary_actor ON events(primary_actor_id);

CREATE TABLE IF NOT EXISTS chronicles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    agent        TEXT NOT NULL,
    language     TEXT NOT NULL DEFAULT 'en',
    title        TEXT,
    body         TEXT NOT NULL,
    model        TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_input_tokens INTEGER,
    cost_usd     REAL,
    created_at   TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chronicles_unique
    ON chronicles(event_id, agent, language);
CREATE INDEX IF NOT EXISTS idx_chronicles_agent ON chronicles(agent);
CREATE INDEX IF NOT EXISTS idx_chronicles_language ON chronicles(language);

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
            # Migrate BEFORE running the canonical schema. SCHEMA_SQL
            # creates a UNIQUE INDEX over (event_id, agent, language);
            # if the legacy chronicles table lacks `language` that
            # statement would fail on an unknown column.
            _migrate(c)
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

    def get_event(self, event_id: str) -> ChronicleEvent | None:
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
        from_year: int | None = None,
        to_year: int | None = None,
        event_type: EventType | None = None,
        character_id: str | None = None,
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

    def has_chronicle(self, event_id: str, agent: str, language: str = "en") -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM chronicles WHERE event_id = ? AND agent = ? AND language = ?",
                (event_id, agent, language),
            ).fetchone()
        return row is not None

    def save_chronicle(
        self,
        *,
        event_id: str,
        agent: str,
        language: str = "en",
        title: str | None,
        body: str,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO chronicles (
                    event_id, agent, language, title, body, model,
                    input_tokens, output_tokens, cached_input_tokens,
                    cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, agent, language) DO UPDATE SET
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
                    language,
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

    def list_chronicles_for_event(
        self,
        event_id: str,
        *,
        language: str | None = None,
    ) -> list[dict]:
        sql = "SELECT agent, language, title, body, model FROM chronicles WHERE event_id = ?"
        params: list = [event_id]
        if language is not None:
            sql += " AND language = ?"
            params.append(language)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def available_languages(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT language FROM chronicles ORDER BY language"
            ).fetchall()
        return [r["language"] for r in rows]

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


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply forward migrations.

    Currently handles: pre-i18n chronicles tables (no `language` column).
    Idempotent — safe to call on a brand-new DB (the chronicles table
    won't exist yet, so PRAGMA returns no rows and we no-op).
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chronicles)").fetchall()]
    if not cols:
        return  # No chronicles table yet; fresh DB.
    if "language" not in cols:
        # Old UNIQUE(event_id, agent) constraint may still exist from the
        # original CREATE TABLE. SQLite can't drop table constraints, so
        # we rebuild the table.
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE chronicles_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'en',
                title TEXT,
                body TEXT NOT NULL,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cached_input_tokens INTEGER,
                cost_usd REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(event_id)
            );
            INSERT INTO chronicles_new
                (id, event_id, agent, language, title, body, model,
                 input_tokens, output_tokens, cached_input_tokens, cost_usd, created_at)
            SELECT
                id, event_id, agent, 'en', title, body, model,
                input_tokens, output_tokens, cached_input_tokens, cost_usd, created_at
            FROM chronicles;
            DROP TABLE chronicles;
            ALTER TABLE chronicles_new RENAME TO chronicles;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chronicles_unique
                ON chronicles(event_id, agent, language);
            CREATE INDEX IF NOT EXISTS idx_chronicles_agent ON chronicles(agent);
            CREATE INDEX IF NOT EXISTS idx_chronicles_language ON chronicles(language);
            COMMIT;
            """
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
