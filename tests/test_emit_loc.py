"""Tests for chronicler.emit_loc -- the Phase 1.1 loc writer.

Pin both the *engine-contract* invariants (BOM, key shape, slot count,
reverse-chrono order, colour tags) and the *Store -> LocEntry* projection
that the CLI subcommand glues together.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chronicler.emit_loc import (
    COLOR_BODY,
    COLOR_TITLE,
    COLOR_YEAR,
    LANG_TABLE,
    MAX_SLOTS_DEFAULT,
    LocEntry,
    collect_entries_from_store,
    render_loc_yaml,
    write_mod_loc,
)
from chronicler.schema import Actor, ChronicleEvent, EventType, Source, make_event_id
from chronicler.storage import Store

# ---- render_loc_yaml --------------------------------------------------


def test_render_namespace_en():
    out = render_loc_yaml([], "en")
    assert out.startswith("l_english:\n")


def test_render_namespace_zh():
    out = render_loc_yaml([], "zh")
    assert out.startswith("l_simp_chinese:\n")


def test_render_rejects_unknown_lang():
    with pytest.raises(ValueError, match="Unsupported lang"):
        render_loc_yaml([], "fr")


def test_render_fills_30_slots_even_when_empty():
    out = render_loc_yaml([], "en")
    for i in range(1, 31):
        assert f' vd_entry_{i:02d}_year:0 ""' in out
        assert f' vd_entry_{i:02d}_title:0 ""' in out
        assert f' vd_entry_{i:02d}_body:0 ""' in out


def test_render_entry_count_key_present_and_zero_when_empty():
    out = render_loc_yaml([], "en")
    assert ' vd_entry_count:0 "0"' in out


def test_render_entry_count_matches_actual_entries():
    entries = [LocEntry(year=1100 - i, title=f"T{i}", body=f"B{i}") for i in range(5)]
    out = render_loc_yaml(entries, "en")
    assert ' vd_entry_count:0 "5"' in out


def test_render_slot_01_is_first_entry_in_input_order():
    # Caller is responsible for reverse-chrono sorting; render does not re-sort.
    entries = [
        LocEntry(year=1099, title="Newest", body="Body N"),
        LocEntry(year=1066, title="Oldest", body="Body O"),
    ]
    out = render_loc_yaml(entries, "en")
    assert "Newest" in out.split("vd_entry_02_year")[0]
    assert "Oldest" in out.split("vd_entry_02_year")[1]


def test_render_applies_color_tags():
    entries = [LocEntry(year=1099, title="Hello", body="World")]
    out = render_loc_yaml(entries, "en")
    assert f"#{COLOR_YEAR} 1099#!" in out
    assert f"#{COLOR_TITLE} Hello#!" in out
    assert f"#{COLOR_BODY} World#!" in out


def test_render_does_not_wrap_empty_fields_in_color_tags():
    # Empty slots must not emit "#color_vd_ink #!" (renders as a stray #!).
    out = render_loc_yaml([], "en")
    assert "#! " not in out  # nothing weird leaked
    assert f"#{COLOR_TITLE} #!" not in out


def test_render_truncates_beyond_max_slots():
    entries = [LocEntry(year=2000 - i, title=f"T{i}", body=f"B{i}") for i in range(35)]
    out = render_loc_yaml(entries, "en")
    # First 30 in -- last 5 dropped.
    assert "T0" in out
    assert "T29" in out
    assert "T30" not in out
    assert ' vd_entry_count:0 "30"' in out


def test_render_respects_custom_max_slots():
    entries = [LocEntry(year=2000 - i, title=f"T{i}", body=f"B{i}") for i in range(5)]
    out = render_loc_yaml(entries, "en", max_slots=3)
    assert ' vd_entry_03_year' in out
    assert ' vd_entry_04_year' not in out
    assert ' vd_entry_count:0 "3"' in out


def test_render_escapes_double_quotes_in_body():
    entries = [LocEntry(year=1099, title='He said "go"', body='also "stop"')]
    out = render_loc_yaml(entries, "en")
    assert r'He said \"go\"' in out
    assert r'also \"stop\"' in out


def test_render_escapes_newlines_in_body():
    entries = [LocEntry(year=1099, title="T", body="line1\nline2")]
    out = render_loc_yaml(entries, "en")
    # Newline inside the YAML value would terminate the string; must be \n.
    assert r"line1\nline2" in out


def test_render_uses_single_space_indent_not_tabs():
    out = render_loc_yaml([LocEntry(year=1099, title="x", body="y")], "en")
    for line in out.splitlines():
        if line.startswith(" "):
            assert "\t" not in line, f"tab leaked in line: {line!r}"


def test_render_chinese_content_passthrough():
    entries = [LocEntry(year=1099, title="开国之君驾崩", body="王安寝于先祖之礼拜堂。")]
    out = render_loc_yaml(entries, "zh")
    assert "开国之君驾崩" in out
    assert "王安寝于先祖之礼拜堂。" in out


# ---- write_mod_loc ----------------------------------------------------


def test_write_mod_loc_creates_correct_paths(tmp_path: Path):
    paths = write_mod_loc(
        tmp_path, [LocEntry(year=1099, title="t", body="b")], ["en", "zh"]
    )
    assert paths["en"] == tmp_path / "localization" / "english" / "vox_dynastica_l_english.yml"
    assert paths["zh"] == tmp_path / "localization" / "simp_chinese" / "vox_dynastica_l_simp_chinese.yml"
    assert paths["en"].exists()
    assert paths["zh"].exists()


def test_write_mod_loc_emits_utf8_bom(tmp_path: Path):
    paths = write_mod_loc(tmp_path, [], ["en"])
    raw = paths["en"].read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "CK3 requires UTF-8 BOM or non-ASCII breaks"


def test_write_mod_loc_round_trips_chinese(tmp_path: Path):
    entry = LocEntry(year=1099, title="开国之君", body="本纪")
    paths = write_mod_loc(tmp_path, [entry], ["zh"])
    # Read back without the BOM and assert the bytes survived.
    raw = paths["zh"].read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"
    text = raw[3:].decode("utf-8")
    assert "开国之君" in text
    assert "本纪" in text


def test_write_mod_loc_is_idempotent(tmp_path: Path):
    entry = LocEntry(year=1099, title="t", body="b")
    write_mod_loc(tmp_path, [entry], ["en"])
    a = (tmp_path / "localization" / "english" / "vox_dynastica_l_english.yml").read_bytes()
    write_mod_loc(tmp_path, [entry], ["en"])
    b = (tmp_path / "localization" / "english" / "vox_dynastica_l_english.yml").read_bytes()
    assert a == b


def test_write_mod_loc_rejects_unknown_lang(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported lang"):
        write_mod_loc(tmp_path, [], ["fr"])


# ---- collect_entries_from_store --------------------------------------


def _mk_event(year: int, salt: str) -> ChronicleEvent:
    actor = Actor(character_id=f"c_{salt}", name=f"Actor {salt}")
    return ChronicleEvent(
        event_id=make_event_id(
            Source.SAVE_IMPORT, EventType.RULER_DEATH, year, salt_parts=[salt]
        ),
        source=Source.SAVE_IMPORT,
        type=EventType.RULER_DEATH,
        year=year,
        primary_actors=[actor],
    )


def test_collect_returns_reverse_chrono_with_only_matching_agent(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    events = [_mk_event(1066, "a"), _mk_event(1099, "b"), _mk_event(1080, "c")]
    store.upsert_events(events)
    for ev in events:
        store.save_chronicle(
            event_id=ev.event_id,
            agent="court_historian",
            language="en",
            title=f"Title {ev.year}",
            body=f"Body {ev.year}",
        )
    out = collect_entries_from_store(
        store, agent="court_historian", language="en"
    )
    assert [e.year for e in out] == [1099, 1080, 1066]
    assert out[0].title == "Title 1099"


def test_collect_skips_events_without_matching_agent(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    ev1 = _mk_event(1066, "a")
    ev2 = _mk_event(1099, "b")
    store.upsert_events([ev1, ev2])
    # Only ev1 gets a court_historian row; ev2 only gets peasant_ballad.
    store.save_chronicle(
        event_id=ev1.event_id, agent="court_historian", language="en",
        title="T1", body="B1",
    )
    store.save_chronicle(
        event_id=ev2.event_id, agent="peasant_ballad", language="en",
        title="T2", body="B2",
    )
    out = collect_entries_from_store(
        store, agent="court_historian", language="en"
    )
    assert [e.year for e in out] == [1066]


def test_collect_skips_empty_chronicles(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    ev = _mk_event(1099, "a")
    store.upsert_event(ev)
    store.save_chronicle(
        event_id=ev.event_id, agent="court_historian", language="en",
        title="   ", body="\n  ",
    )
    out = collect_entries_from_store(store, agent="court_historian", language="en")
    assert out == []


def test_collect_truncates_to_max_entries(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    events = [_mk_event(1000 + i, f"e{i}") for i in range(50)]
    store.upsert_events(events)
    for ev in events:
        store.save_chronicle(
            event_id=ev.event_id, agent="court_historian", language="en",
            title=f"T{ev.year}", body=f"B{ev.year}",
        )
    out = collect_entries_from_store(
        store, agent="court_historian", language="en", max_entries=10
    )
    assert len(out) == 10
    # Newest 10 = years 1040..1049, in descending order.
    assert [e.year for e in out] == list(range(1049, 1039, -1))


def test_collect_respects_year_window(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    events = [_mk_event(y, f"e{y}") for y in (1050, 1066, 1099, 1130)]
    store.upsert_events(events)
    for ev in events:
        store.save_chronicle(
            event_id=ev.event_id, agent="court_historian", language="en",
            title=f"T{ev.year}", body="B",
        )
    out = collect_entries_from_store(
        store, agent="court_historian", language="en",
        from_year=1066, to_year=1099,
    )
    assert [e.year for e in out] == [1099, 1066]


def test_collect_language_filter(tmp_path: Path):
    store = Store(tmp_path / "c.db")
    ev = _mk_event(1099, "a")
    store.upsert_event(ev)
    store.save_chronicle(
        event_id=ev.event_id, agent="court_historian", language="en",
        title="EN", body="en body",
    )
    store.save_chronicle(
        event_id=ev.event_id, agent="court_historian", language="zh",
        title="中", body="中文",
    )
    en_out = collect_entries_from_store(store, agent="court_historian", language="en")
    zh_out = collect_entries_from_store(store, agent="court_historian", language="zh")
    assert en_out[0].title == "EN"
    assert zh_out[0].title == "中"


# ---- contract sanity --------------------------------------------------


def test_max_slots_default_matches_30():
    # GUI hardcodes 30 slots; emit-loc must match.
    assert MAX_SLOTS_DEFAULT == 30


def test_lang_table_covers_en_and_zh():
    assert set(LANG_TABLE) == {"en", "zh"}
