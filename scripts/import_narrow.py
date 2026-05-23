"""Narrow-scope importer: chronicle the player's own house only.

This is the first of three planned scope tiers. The player chooses how
wide the chronicle's eye should be:

  narrow  — only the player's own dynastic house. Births, deaths,
            marriages of house members, plus wars the player fights.
            Suitable for landed rulers who want a family chronicle, and
            for landless adventurers (their bloodline is still the unit).
  middle  — narrow PLUS the lieges of any realms the player has resided
            in (future, planned for landless adventurer playthroughs).
  wide    — every prominent ruler in the known world (the previous default).

This script implements ``narrow``. It auto-detects the player from
``played_character.character`` and filters everything to that house id.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "src"))

from chronicler.parsers.save_import import _make_actor, convert_save_to_json  # noqa: E402
from chronicler.schema import (  # noqa: E402
    Actor,
    ChronicleEvent,
    EventType,
    Faction,
    FactionSide,
    Outcome,
    Source,
    make_event_id,
)
from chronicler.storage import Store  # noqa: E402

MURDER_REASONS = {"death_murder", "death_assassination", "death_poison", "death_duel"}


def _decode_ck3_name(name: str) -> str:
    """CK3 encodes CJK names as ``Pinyin_HEX_HEX...``. Reverse to readable form."""
    if not isinstance(name, str) or "_" not in name:
        return name
    parts = name.split("_")
    head = parts[0]
    cjk = []
    for p in parts[1:]:
        if len(p) == 4 and all(c in "0123456789ABCDEFabcdef" for c in p):
            try:
                cjk.append(chr(int(p, 16)))
                continue
            except ValueError:
                pass
        cjk.append(p)
    cjk_str = "".join(cjk)
    if cjk_str and head:
        return f"{head} {cjk_str}"
    return head or cjk_str


def _parse_date(s):
    if not isinstance(s, str) or "." not in s:
        return None
    try:
        parts = [int(x) for x in s.split(".")]
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
    except (ValueError, IndexError):
        return None
    return None


def _enrich(actor: Actor, *, name_override: str | None = None, titles: list | None = None) -> Actor:
    return actor.model_copy(update={
        "name": _decode_ck3_name(name_override or actor.name),
        "titles": [str(t) for t in (titles or [])][:6],
    })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--from-year", type=int, default=1030)
    ap.add_argument("--to-year", type=int, default=1034)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument(
        "--player",
        type=int,
        default=None,
        help="Override player character id. Default: parsed.played_character.character",
    )
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

    living = parsed.get("living") or {}
    dead = parsed.get("dead_unprunable") or {}
    chars = {**dead, **living}

    # ---- locate player + house ----
    pc = parsed.get("played_character") or {}
    pid = args.player or pc.get("character")
    if pid is None:
        print("[error] no player id; pass --player", file=sys.stderr)
        sys.exit(2)
    pid = int(pid)
    player = chars.get(str(pid))
    if not player:
        print(f"[error] player {pid} not found", file=sys.stderr)
        sys.exit(2)

    house_id = player.get("dynasty_house")
    player_name = _decode_ck3_name(player.get("first_name") or f"Character {pid}")
    print(f"[info] player: {player_name} (id={pid}, house={house_id})", flush=True)

    houses = ((parsed.get("dynasties") or {}).get("dynasty_house") or {})
    house = houses.get(str(house_id)) if isinstance(houses, dict) else None
    house_name = None
    if isinstance(house, dict):
        raw = house.get("name") or ""
        # "dynn_HA_steining" → "Steining"; "dynn_Villeneuve" → "Villeneuve"
        if isinstance(raw, str) and raw.startswith("dynn_"):
            tail = raw[len("dynn_"):]
            # Drop optional CK3 region prefix like "HA_"
            if "_" in tail and len(tail.split("_", 1)[0]) <= 3:
                tail = tail.split("_", 1)[1]
            house_name = tail.replace("_", " ").title()
        else:
            house_name = str(raw)
    print(f"[info] house: {house_name}", flush=True)

    # ---- enumerate house members ----
    house_members = {
        cid: c for cid, c in chars.items()
        if isinstance(c, dict) and c.get("dynasty_house") == house_id
    }
    print(f"[info] house members (living+dead): {len(house_members)}", flush=True)

    events: list[ChronicleEvent] = []

    # ---- family DEATHS in window ----
    for cid, c in house_members.items():
        dd = c.get("dead_data") or {}
        if not isinstance(dd, dict):
            continue
        date = _parse_date(dd.get("date"))
        if not date:
            continue
        y, m, d = date
        if y < args.from_year or y > args.to_year:
            continue
        reason = str(dd.get("reason") or "")
        is_murder = reason in MURDER_REASONS or "murder" in reason or "assassin" in reason
        event_type = EventType.MURDER if is_murder else EventType.RULER_DEATH
        outcome = Outcome.FAILURE if is_murder else Outcome.NATURAL
        actor = _enrich(_make_actor(cid, chars), titles=dd.get("domain") or [])
        # Add relation hint via tags.
        tags = [reason] if reason else []
        tags.append(f"house:{house_name}" if house_name else "house:unknown")
        gov = dd.get("government")
        if gov:
            tags.append(str(gov))
        eid = make_event_id(
            Source.SAVE_IMPORT, event_type, y,
            salt_parts=[cid, reason, str(y), str(m), str(d)],
        )
        events.append(ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=event_type,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=outcome, tags=tags,
            raw_excerpt=json.dumps({
                "dead_data": dd, "first_name": c.get("first_name"),
                "relation_to_player": "house_member",
                "house": house_name,
            }, ensure_ascii=False)[:800],
        ))
    print(f"[info] family deaths in window: {sum(1 for e in events if e.type in (EventType.RULER_DEATH, EventType.MURDER))}", flush=True)

    # ---- family BIRTHS in window (newborns in the house) ----
    n_births = 0
    for cid, c in house_members.items():
        birth = c.get("birth")
        date = _parse_date(birth)
        if not date:
            continue
        y, m, d = date
        if y < args.from_year or y > args.to_year:
            continue
        actor = _enrich(_make_actor(cid, chars))
        # Note parents from family_data if we can find them in chars.
        # birth is recorded on the newborn; parents not directly here.
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.BIRTH, y,
            salt_parts=[cid, "birth", str(y), str(m), str(d)],
        )
        events.append(ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.BIRTH,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=Outcome.SUCCESS,
            tags=[f"house:{house_name}" if house_name else "house:unknown"],
            raw_excerpt=json.dumps({
                "relation_to_player": "house_member",
                "house": house_name,
                "born": birth,
            }, ensure_ascii=False)[:400],
        ))
        n_births += 1
    print(f"[info] family births in window: {n_births}", flush=True)

    # ---- ACTIVE WARS the player is in ----
    wars_root = parsed.get("wars") or {}
    active = wars_root.get("active_wars") if isinstance(wars_root, dict) else None
    war_names = wars_root.get("names") if isinstance(wars_root, dict) else {}
    if not isinstance(war_names, dict):
        war_names = {}
    n_wars = 0
    if isinstance(active, dict):
        for war_id, war in active.items():
            if not isinstance(war, dict):
                continue
            attackers = war.get("attackers") or war.get("attacker") or []
            defenders = war.get("defenders") or war.get("defender") or []
            if not isinstance(attackers, list):
                attackers = [attackers]
            if not isinstance(defenders, list):
                defenders = [defenders]
            all_sides = [str(x) for x in (attackers + defenders) if x is not None]
            if str(pid) not in all_sides:
                # try to find player as participant via nested participants list
                parts = war.get("attacker_participants") or war.get("defender_participants") or []
                if isinstance(parts, list) and str(pid) not in [str(x) for x in parts]:
                    continue
                elif not parts:
                    continue
            # War involves the player.
            start = _parse_date(war.get("start_date")) or _parse_date(war.get("date_start"))
            if not start:
                # fall back to save date so the LLM has something to anchor.
                start = _parse_date(save_date)
            if not start:
                continue
            y, m, d = start
            if y < args.from_year - 5 or y > args.to_year:
                continue
            # name lookup: war.get("name_key") or war.get("name") may be a token
            wname = war.get("name") or war.get("war_name")
            if isinstance(wname, dict):
                wname = wname.get("key")
            if not wname:
                wname = f"war_{war_id}"
            primary = _enrich(_make_actor(str(pid), chars), name_override=player.get("first_name"))
            factions = []
            for a in attackers[:3]:
                factions.append(Faction(name=_decode_ck3_name(_make_actor(str(a), chars).name), side=FactionSide.ATTACKER))
            for de in defenders[:3]:
                factions.append(Faction(name=_decode_ck3_name(_make_actor(str(de), chars).name), side=FactionSide.DEFENDER))
            eid = make_event_id(
                Source.SAVE_IMPORT, EventType.WAR_END, y,
                salt_parts=[str(war_id), str(wname), str(y)],
            )
            events.append(ChronicleEvent(
                event_id=eid, source=Source.SAVE_IMPORT, type=EventType.WAR_END,
                year=y, month=m, day=d,
                primary_actors=[primary],
                factions=factions,
                outcome=Outcome.UNKNOWN,
                tags=["ongoing", str(wname), f"house:{house_name}" if house_name else "house:unknown"],
                raw_excerpt=json.dumps({
                    "status": "ongoing_at_save_time",
                    "save_date": save_date,
                    "war_name_token": wname,
                    "attackers": attackers[:5],
                    "defenders": defenders[:5],
                }, ensure_ascii=False)[:600],
            ))
            n_wars += 1
    print(f"[info] active wars involving player: {n_wars}", flush=True)

    # ---- order + cap ----
    events.sort(key=lambda e: (e.year, e.month or 0, e.day or 0))
    if len(events) > args.max:
        events = events[-args.max:]
        print(f"[info] capped to latest {args.max}", flush=True)
    print(f"[info] total events: {len(events)}", flush=True)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.json), inserted + skipped)
    print(f"[done] inserted={inserted} skipped={skipped} db={args.db}", flush=True)


if __name__ == "__main__":
    main()
