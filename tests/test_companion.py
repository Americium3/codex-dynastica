"""Tests for chronicler.companion -- the Phase 1.2 save-watcher + runner.

The tray UI (chronicler.tray) is *not* tested here; it needs a display
and pystray's loop is hard to drive headlessly. Instead we pin:

*   :class:`SaveWatcher` debounce behaviour under a hand-driven clock
*   :func:`run_pipeline_once` end-to-end with all heavy fns stubbed
*   :class:`CompanionConfig` defaults and OS-aware save-dir guess
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from chronicler.companion import (
    CompanionConfig,
    RunReport,
    SaveWatcher,
    run_pipeline_once,
)
from chronicler.schema import Actor, ChronicleEvent, EventType, Source, make_event_id

# ---- SaveWatcher ------------------------------------------------------


def _touch(path: Path, content: bytes = b"x") -> None:
    path.write_bytes(content)


def test_watcher_rejects_zero_stable_polls(tmp_path: Path):
    with pytest.raises(ValueError):
        SaveWatcher(tmp_path, lambda p: None, stable_polls=0)


def test_watcher_does_not_fire_on_pre_existing_save_after_prime(tmp_path: Path):
    """Files already present at startup must not re-fire -- we only care
    about *new* saves once we're watching."""
    f = tmp_path / "autosave.ck3"
    _touch(f, b"existing")
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=2)
    w.prime()
    w.tick()
    w.tick()
    w.tick()
    assert fired == []


def test_watcher_fires_after_stable_polls_threshold(tmp_path: Path):
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=2)
    w.prime()
    f = tmp_path / "autosave.ck3"
    _touch(f, b"abc")
    w.tick()  # first time we see it: pending, count=1
    assert fired == []
    w.tick()  # same sig: count=2 -> fires
    assert fired == [f]


def test_watcher_does_not_refire_for_same_signature(tmp_path: Path):
    """Once we've narrated a save, don't narrate it again on every tick
    for the rest of the session."""
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=2)
    w.prime()
    f = tmp_path / "autosave.ck3"
    _touch(f, b"abc")
    w.tick()
    w.tick()  # fires
    for _ in range(5):
        w.tick()
    assert fired == [f]


def test_watcher_refires_when_file_is_rewritten(tmp_path: Path):
    """The autosave overwrite cycle: same path, new (size, mtime).
    Must fire again once the new write stabilises."""
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=2)
    w.prime()
    f = tmp_path / "autosave.ck3"
    _touch(f, b"v1")
    w.tick()
    w.tick()
    assert fired == [f]

    # Simulate a fresh write with a different size *and* mtime so the sig
    # genuinely changes regardless of filesystem mtime granularity.
    os.utime(f, ns=(0, 0))  # force old mtime
    _touch(f, b"v2-larger-content")
    w.tick()
    w.tick()
    assert fired == [f, f]


def test_watcher_holds_until_file_stops_growing(tmp_path: Path):
    """CK3 writes saves over several seconds. We must not parse mid-write."""
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=3)
    w.prime()
    f = tmp_path / "autosave.ck3"

    _touch(f, b"a")
    w.tick()           # pending, count=1
    _touch(f, b"ab")   # still growing
    w.tick()           # sig changed: pending reset, count=1
    _touch(f, b"abc")
    w.tick()           # sig changed again: count=1
    assert fired == []
    # Now writes stop:
    w.tick()
    w.tick()
    w.tick()
    assert fired == [f]


def test_watcher_paused_skips_ticks(tmp_path: Path):
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=1)
    w.prime()
    w.paused = True
    f = tmp_path / "autosave.ck3"
    _touch(f, b"x")
    w.tick()
    w.tick()
    assert fired == []
    w.paused = False
    w.tick()
    w.tick()
    assert fired == [f]


def test_watcher_glob_filters_non_ck3_files(tmp_path: Path):
    fired: list[Path] = []
    w = SaveWatcher(tmp_path, fired.append, stable_polls=1, file_glob="*.ck3")
    w.prime()
    (tmp_path / "junk.txt").write_bytes(b"x")
    (tmp_path / "autosave.ck3").write_bytes(b"x")
    w.tick()
    assert [p.name for p in fired] == ["autosave.ck3"]


def test_watcher_callback_exception_does_not_kill_loop(tmp_path: Path):
    calls: list[Path] = []

    def boom(p: Path) -> None:
        calls.append(p)
        raise RuntimeError("simulated parse failure")

    w = SaveWatcher(tmp_path, boom, stable_polls=1)
    w.prime()
    _touch(tmp_path / "autosave.ck3", b"x")
    # Must not raise:
    w.tick()
    assert len(calls) == 1
    # And next tick still works on a different file:
    _touch(tmp_path / "named.ck3", b"y")
    w.tick()
    assert len(calls) == 2


def test_watcher_handles_missing_save_dir(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    w = SaveWatcher(missing, lambda p: None, stable_polls=1)
    w.prime()
    assert w.tick() == []  # no crash


def test_watcher_returns_paths_that_fired_this_tick(tmp_path: Path):
    w = SaveWatcher(tmp_path, lambda p: None, stable_polls=1)
    w.prime()
    _touch(tmp_path / "a.ck3", b"x")
    _touch(tmp_path / "b.ck3", b"y")
    fired = w.tick()
    assert sorted(p.name for p in fired) == ["a.ck3", "b.ck3"]


# ---- run_pipeline_once -----------------------------------------------


def _mk_event(year: int, salt: str) -> ChronicleEvent:
    return ChronicleEvent(
        event_id=make_event_id(
            Source.SAVE_IMPORT, EventType.RULER_DEATH, year, salt_parts=[salt]
        ),
        source=Source.SAVE_IMPORT,
        type=EventType.RULER_DEATH,
        year=year,
        primary_actors=[Actor(character_id=f"c_{salt}", name=f"Actor {salt}")],
    )


@dataclass
class _FakeStats:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0


def _make_config(tmp_path: Path, **overrides: Any) -> CompanionConfig:
    return CompanionConfig(
        mod_dir=tmp_path / "mod",
        db_path=tmp_path / "chronicle.db",
        save_dir=tmp_path / "saves",
        languages=["en"],
        backend="dry-run",
        **overrides,
    )


def test_run_pipeline_writes_loc_and_returns_report(tmp_path: Path):
    save = tmp_path / "saves" / "autosave.ck3"
    save.parent.mkdir()
    save.write_bytes(b"fake save bytes")
    config = _make_config(tmp_path)

    fake_events = [_mk_event(1099, "a"), _mk_event(1066, "b")]

    def fake_parse(path):
        assert path == save
        return {"fake": "parsed"}

    def fake_extract(parsed):
        return iter(fake_events)

    def fake_generate(*, store, agents, languages):  # noqa: ARG001
        # Pretend the agent generated one row per event per language.
        for ev in fake_events:
            for lang in languages:
                store.save_chronicle(
                    event_id=ev.event_id,
                    agent="court_historian",
                    language=lang,
                    title=f"T {ev.year}",
                    body=f"B {ev.year}",
                )
        return _FakeStats(generated=len(fake_events) * len(languages))

    def fake_make_agents(cfg):  # noqa: ARG001
        # Returning (None, None) is fine -- build_agents() is the next call
        # but we monkey-patched generate_range_fn so build_agents won't run.
        # Actually, generate_range_fn IS called, but it ignores the agents.
        from chronicler.agents import DryRunClient
        return DryRunClient(), None

    report = run_pipeline_once(
        save, config,
        parse_save_fn=fake_parse,
        extract_events_fn=fake_extract,
        generate_range_fn=fake_generate,
        make_agents_fn=fake_make_agents,
    )

    assert report.ok
    assert report.events_new == 2
    assert report.events_skipped == 0
    assert report.chronicles_generated == 2
    assert len(report.loc_files_written) == 1
    en_path = config.mod_dir / "localization" / "english" / "vox_dynastica_l_english.yml"
    assert en_path.exists()
    raw = en_path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"  # BOM
    text = raw[3:].decode("utf-8")
    # Newest year (1099) goes to slot 01.
    assert "T 1099" in text.split("vd_entry_02_year")[0]


def test_run_pipeline_catches_parse_errors_into_report(tmp_path: Path):
    save = tmp_path / "saves" / "autosave.ck3"
    save.parent.mkdir()
    save.write_bytes(b"x")
    (tmp_path / "mod").mkdir()
    config = _make_config(tmp_path)

    def boom(path):  # noqa: ARG001
        raise RuntimeError("rakaly choked on this byte")

    report = run_pipeline_once(
        save, config,
        parse_save_fn=boom,
        extract_events_fn=lambda _p: iter([]),
        generate_range_fn=lambda **_kw: _FakeStats(),
        make_agents_fn=lambda _c: (None, None),
    )
    assert not report.ok
    assert "rakaly choked" in (report.error or "")
    assert report.loc_files_written == []


def test_run_pipeline_skips_generation_when_no_new_events(tmp_path: Path):
    """If a save introduces no new event_ids (player loaded an old save),
    don't pay the LLM cost. emit-loc still rewrites the YAML so a stale
    file gets refreshed (idempotent)."""
    save = tmp_path / "saves" / "autosave.ck3"
    save.parent.mkdir()
    save.write_bytes(b"x")
    config = _make_config(tmp_path)

    # Pre-seed the store with one event so the next "import" hits skip path.
    from chronicler.storage import Store
    existing = _mk_event(1099, "a")
    Store(config.db_path).upsert_event(existing)

    generate_called = {"n": 0}

    def fake_generate(**_kw):
        generate_called["n"] += 1
        return _FakeStats(generated=999)

    report = run_pipeline_once(
        save, config,
        parse_save_fn=lambda _p: None,
        extract_events_fn=lambda _p: iter([existing]),
        generate_range_fn=fake_generate,
        make_agents_fn=lambda _c: (None, None),
    )
    assert report.ok
    assert report.events_new == 0
    assert report.events_skipped == 1
    assert generate_called["n"] == 0  # crucial -- no LLM call


# ---- CompanionConfig --------------------------------------------------


def test_default_save_dir_uses_userprofile_on_windows(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Mock")
    p = CompanionConfig.default_save_dir(os_name="nt")
    assert "Paradox Interactive" in str(p)
    assert "Crusader Kings III" in str(p)
    assert "save games" in str(p)


def test_default_save_dir_falls_back_on_posix():
    # ``os_name="posix"`` avoids monkeypatching the global os.name (which
    # breaks pytest's Path machinery on Windows).
    p = CompanionConfig.default_save_dir(os_name="posix")
    assert "Paradox Interactive" in str(p)
    assert "Crusader Kings III" in str(p)


def test_run_report_is_immutable():
    """Frozen so callers can stash it (tray history list) without worrying
    about later mutation."""
    r = RunReport(
        save_path=Path("x"), events_new=0, events_skipped=0,
        chronicles_generated=0, loc_files_written=[], ok=True,
    )
    with pytest.raises((AttributeError, TypeError)):
        r.events_new = 5  # type: ignore[misc]
