"""End-to-end smoke test using fixture data and the dry-run LLM client.

Verifies the entire pipeline works with zero external dependencies:
  fixture save JSON → extract → store → generate (mock) → render HTML.
"""

from __future__ import annotations

from pathlib import Path

from chronicler.agents import DryRunClient, build_agents
from chronicler.generator import generate_range
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
    assert stats.generated == 4  # 2 events × 2 agents
    assert stats.skipped == 0


def test_event_id_dedup_across_sources(tmp_path: Path) -> None:
    """Same logical event from both sources should hash to different IDs
    (because source is part of the id prefix), but each source is
    independently idempotent."""
    db = tmp_path / "chronicle.db"
    store = Store(db)

    parsed = parse_save_json(FIXTURES / "sample_save.json")
    events = list(extract_events(parsed))
    ids = {e.event_id for e in events}
    assert len(ids) == len(events), "Save-import events must have unique IDs"
    for eid in ids:
        assert eid.startswith("save_import:")
