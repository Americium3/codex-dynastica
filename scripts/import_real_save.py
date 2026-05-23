"""Real-save import driver, scoped to *notable* recent deaths.

Lessons from probing 澜皇帝_1034:
  - 93,444 dead characters total, most are flavor NPCs with only a date.
  - The interesting ones have ``dead_data.reason`` AND (``domain`` or ``liege_title``).
  - The save has no ``past_wars`` / ``title_history``, so we can't extract those.
  - Death dates span the whole 867→1034 game span.

Strategy: keep only landed/titled deaths in the last ~5 in-game years before the
save date, cap at --max events. That gives the LLM a tractable batch.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "src"))

from chronicler.parsers.save_import import (  # noqa: E402
    _make_actor,
    convert_save_to_json,
)
from chronicler.schema import (  # noqa: E402
    ChronicleEvent,
    EventType,
    Outcome,
    Source,
    make_event_id,
)
from chronicler.storage import Store  # noqa: E402

MURDER_REASONS = {"death_murder", "death_assassination", "death_poison", "death_duel"}


def _decode_ck3_name(name: str) -> str:
    """CK3 saves encode CJK names as ``Pinyin_HEX_HEX...`` where each HEX is a
    4-digit uppercase Unicode code point. ``Junyi_541B_5F08`` → ``Junyi 君弨``.
    Leaves plain ASCII names untouched.
    """
    if not isinstance(name, str) or "_" not in name:
        return name
    parts = name.split("_")
    head = parts[0]
    cjk = []
    for p in parts[1:]:
        if len(p) == 4 and all(c in "0123456789ABCDEFabcdef" for c in p):
            try:
                cjk.append(chr(int(p, 16)))
            except ValueError:
                cjk.append(p)
        else:
            cjk.append(p)
    cjk_str = "".join(cjk)
    if cjk_str and head:
        return f"{head} {cjk_str}"
    return head or cjk_str


def _parse_date(s):
    if not isinstance(s, str) or "." not in s:
        return None
    parts = s.split(".")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--from-year", type=int, default=1030, help="Lower bound (inclusive).")
    ap.add_argument("--to-year", type=int, default=1034)
    ap.add_argument("--max", type=int, default=25)
    args = ap.parse_args()

    if args.json is None and args.save is None:
        ap.error("pass --json or --save")
    if args.json is None:
        args.json = convert_save_to_json(args.save)

    t0 = time.perf_counter()
    print(f"[load] {args.json}", flush=True)
    parsed = json.loads(Path(args.json).read_text(encoding="utf-8"))
    print(f"[load] {time.perf_counter() - t0:.1f}s", flush=True)

    save_date = parsed.get("date") or "1034.1.1"
    print(f"[info] save date: {save_date}", flush=True)

    dead = parsed.get("dead_unprunable") or {}
    living = parsed.get("living") or {}
    chars = {**dead, **living}
    print(f"[info] characters indexed: {len(chars)} (dead={len(dead)}, living={len(living)})", flush=True)

    # Build candidate list: notable, recent.
    candidates: list[tuple[tuple[int, int, int], str, dict]] = []
    for cid, c in dead.items():
        dd = c.get("dead_data") or {}
        reason = dd.get("reason")
        if not reason:
            continue
        if not (dd.get("domain") or dd.get("liege_title")):
            continue
        date = _parse_date(dd.get("date"))
        if not date:
            continue
        y, m, d = date
        if y < args.from_year or y > args.to_year:
            continue
        candidates.append((date, str(cid), c))

    candidates.sort(key=lambda t: t[0])
    print(f"[info] {len(candidates)} notable deaths in {args.from_year}-{args.to_year}", flush=True)

    if not candidates:
        print("[warn] no candidates — widen --from-year/--to-year or relax filter", flush=True)
        return

    if len(candidates) > args.max:
        # Keep the latest N (those closest to the save's "present").
        candidates = candidates[-args.max :]
        print(f"[info] capped to latest {args.max}", flush=True)

    events: list[ChronicleEvent] = []
    for (year, month, day), cid, c in candidates:
        dd = c.get("dead_data") or {}
        reason = str(dd.get("reason") or "")
        is_murder = reason in MURDER_REASONS or "murder" in reason or "assassin" in reason
        event_type = EventType.MURDER if is_murder else EventType.RULER_DEATH
        outcome = Outcome.FAILURE if is_murder else Outcome.NATURAL

        # Enrich actor with titles taken from dead_data.domain rather than landed_data.
        actor = _make_actor(cid, chars)
        # Decode CK3-encoded CJK name; add held titles for context.
        domain_titles = dd.get("domain") or []
        actor = actor.model_copy(update={
            "name": _decode_ck3_name(actor.name),
            "titles": [str(t) for t in (domain_titles if isinstance(domain_titles, list) else [])][:6],
        })

        tags = [reason]
        gov = dd.get("government")
        if gov:
            tags.append(str(gov))
        flavor = dd.get("flavor")
        if flavor:
            tags.append(str(flavor))

        eid = make_event_id(
            Source.SAVE_IMPORT, event_type, year,
            salt_parts=[cid, reason, str(year), str(month), str(day)],
        )
        events.append(ChronicleEvent(
            event_id=eid,
            source=Source.SAVE_IMPORT,
            type=event_type,
            year=year,
            month=month,
            day=day,
            primary_actors=[actor],
            outcome=outcome,
            tags=tags,
            raw_excerpt=json.dumps({"dead_data": dd, "first_name": c.get("first_name")}, ensure_ascii=False)[:800],
        ))

    print(f"[info] built {len(events)} events", flush=True)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.json), inserted + skipped)
    print(f"[done] inserted={inserted} skipped={skipped} db={args.db}", flush=True)


if __name__ == "__main__":
    main()
