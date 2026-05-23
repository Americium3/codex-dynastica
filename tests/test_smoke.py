"""End-to-end smoke test using fixture data and the dry-run LLM client.

Verifies the entire pipeline works with zero external dependencies:
  fixture save JSON → extract → store → generate (mock) → render HTML.
Both English and Chinese paths are exercised.
"""

from __future__ import annotations

from pathlib import Path

from chronicler.agents import DryRunClient, build_agents
from chronicler.generator import generate_range
from chronicler.i18n import _, set_locale
from chronicler.parsers.live_hook import iter_events_from_file
from chronicler.parsers.save_import import extract_events, parse_save_json
from chronicler.render import render_html
from chronicler.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def test_save_import_to_render(tmp_path: Path) -> None:
    db = tmp_path / "chronicle.db"
    store = Store(db)

    parsed = parse_save_json(FIXTURES / "sample_save.json")
    events = list(extract_events(parsed))
    assert events, "Expected at least one event from the sample save"

    inserted, skipped = store.upsert_events(events)
    assert inserted == len(events)
    assert skipped == 0

    # Idempotency: re-importing the same fixture must not duplicate.
    inserted2, skipped2 = store.upsert_events(events)
    assert inserted2 == 0
    assert skipped2 == len(events)

    client = DryRunClient()
    agents = build_agents(client)
    stats = generate_range(store=store, agents=agents)
    assert stats.generated == len(events) * len(agents)
    assert stats.failed == 0

    out = tmp_path / "out.html"
    render_html(store, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Chronicles of the Realm" in text
    assert "Court Chronicle" in text
    assert "Folk Ballad" in text


def test_live_hook_jsonl(tmp_path: Path) -> None:
    db = tmp_path / "chronicle.db"
    store = Store(db)

    count = 0
    for ev in iter_events_from_file(FIXTURES / "sample_events.jsonl"):
        if store.upsert_event(ev):
            count += 1
    assert count == 2

    client = DryRunClient()
    agents = build_agents(client)
    stats = generate_range(store=store, agents=agents)
    assert stats.generated == 4  # 2 events × 2 agents × 1 language
    assert stats.skipped == 0


def test_event_id_dedup_across_sources(tmp_path: Path) -> None:
    db = tmp_path / "chronicle.db"
    Store(db)  # smoke-create the DB; constructor exercises schema migration
    parsed = parse_save_json(FIXTURES / "sample_save.json")
    events = list(extract_events(parsed))
    ids = {e.event_id for e in events}
    assert len(ids) == len(events), "Save-import events must have unique IDs"
    for eid in ids:
        assert eid.startswith("save_import:")


def test_bilingual_generation_and_render(tmp_path: Path) -> None:
    """Generate both EN and ZH chronicles for the same events; ensure
    they are stored separately and each language renders its own HTML."""
    db = tmp_path / "chronicle.db"
    store = Store(db)
    parsed = parse_save_json(FIXTURES / "sample_save.json")
    events = list(extract_events(parsed))
    store.upsert_events(events)

    client = DryRunClient()
    agents = build_agents(client)
    stats = generate_range(
        store=store, agents=agents, languages=("en", "zh")
    )
    # 2 agents × N events × 2 languages
    assert stats.generated == len(events) * len(agents) * 2
    assert stats.failed == 0

    # Storage round-trip: each event has 4 chronicles (2 agents × 2 langs).
    sample_eid = events[0].event_id
    all_rows = store.list_chronicles_for_event(sample_eid)
    assert len(all_rows) == 4
    en_rows = store.list_chronicles_for_event(sample_eid, language="en")
    zh_rows = store.list_chronicles_for_event(sample_eid, language="zh")
    assert len(en_rows) == 2
    assert len(zh_rows) == 2

    assert set(store.available_languages()) == {"en", "zh"}

    # Render each language; chrome must localize.
    en_out = tmp_path / "out_en.html"
    zh_out = tmp_path / "out_zh.html"
    render_html(store, en_out, language="en")
    render_html(store, zh_out, language="zh")
    en_text = en_out.read_text(encoding="utf-8")
    zh_text = zh_out.read_text(encoding="utf-8")
    assert "Court Chronicle" in en_text
    assert "宫廷史录" in zh_text
    assert "Folk Ballad" in en_text
    assert "民间歌谣" in zh_text
    assert 'lang="en"' in en_text
    assert 'lang="zh-CN"' in zh_text


def test_i18n_helper_lookup() -> None:
    set_locale("en")
    en = _("html.col.court_historian")
    set_locale("zh")
    zh = _("html.col.court_historian")
    assert en == "Court Chronicle"
    assert zh == "宫廷史录"
    # Unknown key falls back to itself (does not raise).
    set_locale("zh")
    assert _("unknown.key.nonexistent") == "unknown.key.nonexistent"
    set_locale("en")


def test_storage_migration_from_pre_i18n_schema(tmp_path: Path) -> None:
    """A DB created without the `language` column must transparently
    upgrade on first open; existing rows should be stamped 'en'."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, source TEXT, type TEXT, year INTEGER,
            primary_actor_id TEXT, primary_actor_name TEXT,
            payload TEXT, created_at TEXT
        );
        CREATE TABLE chronicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            title TEXT, body TEXT NOT NULL, model TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            cached_input_tokens INTEGER, cost_usd REAL, created_at TEXT NOT NULL,
            UNIQUE(event_id, agent)
        );
        INSERT INTO chronicles (event_id, agent, title, body, created_at)
        VALUES ('save_import:war_end:1066:abc123', 'court_historian',
                'Of the Battle', 'And it came to pass...', '2026-05-23T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    # Opening the Store should migrate.
    store = Store(db)
    # The legacy row survives and is stamped 'en'.
    rows = store.list_chronicles_for_event("save_import:war_end:1066:abc123")
    assert len(rows) == 1
    assert rows[0]["language"] == "en"
    # And the new language column accepts inserts.
    store.save_chronicle(
        event_id="save_import:war_end:1066:abc123",
        agent="court_historian",
        language="zh",
        title="某战之记",
        body="某年某月，王师...",
    )
    assert set(store.available_languages()) == {"en", "zh"}
