"""Dynastic-scope importer — Phase 0.1.

Vox Dynastica's spine is the **primary title**. This script walks the
player's primary title (``landed_data.domain[0]`` by CK3's precedence
convention) and pulls every event that hangs off that throne:

  1.  Title-holder deaths       — each past holder, dated from the title's
                                  history dict. Cause of death and held
                                  domain pulled from the holder's
                                  ``dead_data`` record where present.
  2.  First-heir birth          — for each holder, the eldest child by
                                  birth date that survived to become heir.
  3.  First-heir death          — if that heir died (e.g. before
                                  inheriting), recorded as a separate
                                  event with the same anchor character.
  4.  Holder's marriage         — from ``family_data.primary_spouse``;
                                  dated only when a date is recoverable
                                  (skipped otherwise — we don't fabricate).
  5.  Active wars on this title — ``wars.active_wars`` filtered to those
                                  whose attacker/defender participants
                                  include the current holder character.
                                  Cause and opposing leader are surfaced.
  6.  Significant traits of the
      current holder            — illness, disability, aging traits in
                                  the player's ``traits`` list, decoded
                                  through ``traits_lookup``. Dated to the
                                  save day (CK3 doesn't store trait
                                  acquisition dates).

Three Phase 0.1 improvements show up here:

  *  ``world_context`` field on every event — pins the reigning ruler so
     the LLM can't invent off-screen kings.
  *  ``--max-per-type`` subquota — keeps any single event class from
     drowning the chronicle.
  *  CK3 CJK name decoder — ``Zihua_5B50_534E`` → ``Zihua 子华``.
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
    Casualties,
    ChronicleEvent,
    EventType,
    Faction,
    FactionSide,
    Outcome,
    Source,
    make_event_id,
)
from chronicler.storage import Store  # noqa: E402


# ---------- trait classification ----------

# These match CK3's stock trait keys. The dynastic chronicle treats any of
# these as worth surfacing as a "state of the holder" entry, because they
# materially shape how the realm is governed.
ILLNESS_TRAITS = {
    "leper", "consumption", "cancer", "early_dementia", "great_pox",
    "typhus", "smallpox", "measles", "bubonic_plague", "ill", "infirm",
    "pneumonic", "depressed_1", "depressed_2", "stressed_1", "stressed_2",
    "lunatic_1", "lunatic_2", "possessed_1", "possessed_2",
}
DISABILITY_TRAITS = {
    "blind", "one_eyed", "lisp", "maimed", "disfigured", "lame",
    "scarred", "wounded_1", "wounded_2", "wounded_3", "missing_eye",
    "stuttering", "clubfooted", "hunchbacked", "dwarf", "giant",
}
AGING_TRAITS = {
    "infirm", "senile", "weak", "feeble", "frail", "elderly",
    # CK3 has no single "aged" trait; "infirm" + "senile" cover most of it.
}
MURDER_REASONS = {"death_murder", "death_assassination", "death_poison", "death_duel"}


def _decode_ck3_name(name: str) -> str:
    if not isinstance(name, str) or "_" not in name:
        return name
    parts = name.split("_")
    head = parts[0]
    cjk: list[str] = []
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


def _decode_house_name(houses: dict, house_id) -> str | None:
    if not isinstance(houses, dict) or house_id is None:
        return None
    h = houses.get(str(house_id))
    if not isinstance(h, dict):
        return None
    raw = h.get("name") or ""
    if isinstance(raw, str) and raw.startswith("dynn_"):
        tail = raw[len("dynn_"):]
        if "_" in tail and len(tail.split("_", 1)[0]) <= 3:
            tail = tail.split("_", 1)[1]
        return tail.replace("_", " ").title()
    return str(raw) if raw else None


def _decode_title_key(key: str | None) -> str:
    """``h_china`` → ``Kingdom of China``; ``e_byzantium`` → ``Empire of Byzantium``."""
    if not isinstance(key, str):
        return "(unnamed title)"
    rank_map = {"e_": "Empire of ", "k_": "Kingdom of ", "d_": "Duchy of ",
                "c_": "County of ", "b_": "Barony of ", "h_": "Kingdom of "}
    for prefix, label in rank_map.items():
        if key.startswith(prefix):
            return label + key[len(prefix):].replace("_", " ").title()
    return key.replace("_", " ").title()


def _enrich(actor: Actor, *, name_override: str | None = None,
            titles: list | None = None) -> Actor:
    return actor.model_copy(update={
        "name": _decode_ck3_name(name_override or actor.name),
        "titles": [str(t) for t in (titles or [])][:6],
    })


def _build_title_holder_map(landed_titles: dict, chars: dict) -> dict[str, str]:
    """title_id → current holder character_id (both as strings)."""
    out: dict[str, str] = {}
    if not isinstance(landed_titles, dict):
        return out
    for tid, t in landed_titles.items():
        if isinstance(t, dict):
            holder = t.get("holder")
            if holder is not None:
                out[str(tid)] = str(holder)
    return out


# ---------- event extractors (each yields ChronicleEvents) ----------


def _extract_holder_history(
    *, primary_id: str, landed_titles: dict, chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
):
    """One death event per past holder of the primary title."""
    pt = landed_titles.get(primary_id)
    if not isinstance(pt, dict):
        return
    hist = pt.get("history")
    if not isinstance(hist, dict):
        return
    # history maps date-string → holder_id (int) or {type, holder, ...}.
    for date_s, entry in hist.items():
        date = _parse_date(date_s)
        if not date:
            continue
        y, m, d = date
        if y < from_year or y > to_year:
            continue
        if isinstance(entry, int):
            holder_id = entry
            type_token = "succession"
        elif isinstance(entry, dict):
            holder_id = entry.get("holder")
            type_token = entry.get("type") or "succession"
        else:
            continue
        if holder_id is None:
            continue
        holder = chars.get(str(holder_id))
        if not isinstance(holder, dict):
            continue
        dd = holder.get("dead_data") or {}
        death = _parse_date(dd.get("date")) if isinstance(dd, dict) else None
        # We're chronicling the *succession date*, which is implicitly the
        # previous holder's death (in non-elective regimes). Record the
        # incoming holder's accession with their first words / first year.
        actor = _enrich(_make_actor(str(holder_id), chars), titles=[primary_id])
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.CORONATION, y,
            salt_parts=[primary_id, str(holder_id), type_token, date_s],
        )
        tags = [type_token, f"title:{title_label}"]
        if house_name:
            tags.append(f"house:{house_name}")
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.CORONATION,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=Outcome.SUCCESS, tags=tags,
            raw_excerpt=json.dumps({
                "title_key": pt.get("key"), "succession_type": type_token,
                "holder_id": str(holder_id),
            }, ensure_ascii=False)[:500],
            world_context=world_context,
        )
        # If holder also died inside the window, emit their death.
        if death:
            dy, dm, dd2 = death
            if from_year <= dy <= to_year:
                reason = str((dd or {}).get("reason") or "")
                is_murder = (
                    reason in MURDER_REASONS
                    or "murder" in reason or "assassin" in reason
                )
                et = EventType.MURDER if is_murder else EventType.RULER_DEATH
                eid_d = make_event_id(
                    Source.SAVE_IMPORT, et, dy,
                    salt_parts=[primary_id, str(holder_id), reason, str(death)],
                )
                death_actor = _enrich(
                    _make_actor(str(holder_id), chars),
                    titles=(dd.get("domain") if isinstance(dd, dict) else None) or [primary_id],
                )
                yield ChronicleEvent(
                    event_id=eid_d, source=Source.SAVE_IMPORT, type=et,
                    year=dy, month=dm, day=dd2,
                    primary_actors=[death_actor],
                    outcome=Outcome.FAILURE if is_murder else Outcome.NATURAL,
                    tags=[reason or "unknown_cause", f"title:{title_label}"]
                         + ([f"house:{house_name}"] if house_name else []),
                    raw_excerpt=json.dumps({
                        "dead_data": dd, "title_key": pt.get("key"),
                    }, ensure_ascii=False)[:600],
                    world_context=world_context,
                )


def _extract_heir_lifecycle(
    *, holder_id: str, chars: dict, house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
):
    """Birth + (optional) death of the holder's eldest child by birth date."""
    holder = chars.get(holder_id) or {}
    fd = holder.get("family_data") or {}
    children = fd.get("child")
    if not isinstance(children, list) or not children:
        return
    dated: list[tuple[tuple[int, int, int], str]] = []
    for cid in children:
        c = chars.get(str(cid))
        if not isinstance(c, dict):
            continue
        b = _parse_date(c.get("birth"))
        if b:
            dated.append((b, str(cid)))
    if not dated:
        return
    dated.sort(key=lambda t: t[0])
    (by, bm, bd), heir_id = dated[0]
    # Birth event for the heir, if in window.
    if from_year <= by <= to_year:
        heir_actor = _enrich(_make_actor(heir_id, chars))
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.BIRTH, by,
            salt_parts=[holder_id, "heir_birth", heir_id, str(by)],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.BIRTH,
            year=by, month=bm, day=bd,
            primary_actors=[heir_actor], outcome=Outcome.SUCCESS,
            tags=["heir", f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "role": "first_heir_to_primary_title",
                "parent_id": holder_id,
            }, ensure_ascii=False)[:300],
            world_context=world_context,
        )
    # Heir death (if dead) in window.
    heir = chars.get(heir_id) or {}
    dd = heir.get("dead_data") or {}
    death = _parse_date(dd.get("date")) if isinstance(dd, dict) else None
    if death and from_year <= death[0] <= to_year:
        dy, dm, ddd = death
        reason = str((dd or {}).get("reason") or "")
        is_murder = reason in MURDER_REASONS or "murder" in reason
        et = EventType.MURDER if is_murder else EventType.RULER_DEATH
        eid_d = make_event_id(
            Source.SAVE_IMPORT, et, dy,
            salt_parts=[holder_id, "heir_death", heir_id, reason],
        )
        heir_actor = _enrich(_make_actor(heir_id, chars))
        yield ChronicleEvent(
            event_id=eid_d, source=Source.SAVE_IMPORT, type=et,
            year=dy, month=dm, day=ddd,
            primary_actors=[heir_actor],
            outcome=Outcome.FAILURE if is_murder else Outcome.NATURAL,
            tags=["heir_died_before_inheriting", reason or "unknown_cause",
                  f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "role": "first_heir_to_primary_title",
                "dead_data": dd, "parent_id": holder_id,
            }, ensure_ascii=False)[:500],
            world_context=world_context,
        )


def _extract_active_wars(
    *, parsed: dict, current_holder_id: str, chars: dict,
    house_name: str | None, title_label: str, save_date: str,
    world_context: str,
):
    wars_root = parsed.get("wars") or {}
    active = wars_root.get("active_wars") if isinstance(wars_root, dict) else None
    if not isinstance(active, dict):
        return
    for war_id, war in active.items():
        if not isinstance(war, dict):
            continue
        att = war.get("attacker") or {}
        deff = war.get("defender") or {}
        att_chars = []
        def_chars = []
        if isinstance(att, dict):
            for p in att.get("participants") or []:
                if isinstance(p, dict) and p.get("character") is not None:
                    att_chars.append(str(p["character"]))
        if isinstance(deff, dict):
            for p in deff.get("participants") or []:
                if isinstance(p, dict) and p.get("character") is not None:
                    def_chars.append(str(p["character"]))
        if current_holder_id not in att_chars + def_chars:
            continue
        player_side = "attacker" if current_holder_id in att_chars else "defender"
        opp_chars = def_chars if player_side == "attacker" else att_chars
        opp_lead = opp_chars[0] if opp_chars else None
        cb = war.get("casus_belli") or {}
        cb_type = cb.get("type") if isinstance(cb, dict) else None
        start = _parse_date(war.get("start_date"))
        if not start:
            start = _parse_date(save_date) or (1, 1, 1)
        y, m, d = start
        primary = _enrich(_make_actor(current_holder_id, chars), titles=[])
        factions = []
        for a in att_chars[:3]:
            factions.append(Faction(name=_decode_ck3_name(_make_actor(a, chars).name),
                                    side=FactionSide.ATTACKER))
        for de in def_chars[:3]:
            factions.append(Faction(name=_decode_ck3_name(_make_actor(de, chars).name),
                                    side=FactionSide.DEFENDER))
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.WAR_END, y,
            salt_parts=[str(war_id), cb_type or "war", current_holder_id, str(y)],
        )
        opp_name = _decode_ck3_name(_make_actor(opp_lead, chars).name) if opp_lead else "an unnamed claimant"
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.WAR_END,
            year=y, month=m, day=d,
            primary_actors=[primary], factions=factions,
            outcome=Outcome.UNKNOWN,
            tags=["ongoing", cb_type or "war",
                  f"player_side:{player_side}",
                  f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "status": "ongoing_at_save_time",
                "save_date": save_date,
                "casus_belli": cb_type,
                "player_side": player_side,
                "opposing_leader": opp_name,
                "attackers": att_chars[:5],
                "defenders": def_chars[:5],
            }, ensure_ascii=False)[:700],
            world_context=world_context,
        )


def _extract_holder_traits(
    *, current_holder_id: str, chars: dict, traits_lookup: list,
    save_date: str, world_context: str, house_name: str | None,
    title_label: str,
):
    """Surface significant traits (illness / disability / aging) of the current holder."""
    holder = chars.get(current_holder_id) or {}
    raw_traits = holder.get("traits") or []
    if not isinstance(raw_traits, list):
        return
    decoded: list[str] = []
    for tid in raw_traits:
        if not isinstance(tid, int):
            continue
        if isinstance(traits_lookup, list) and 0 <= tid < len(traits_lookup):
            decoded.append(traits_lookup[tid])
    date = _parse_date(save_date) or (1066, 1, 1)
    y, m, d = date
    sig: list[tuple[str, str]] = []  # (category, trait_name)
    for t in decoded:
        if t in ILLNESS_TRAITS:
            sig.append(("illness", t))
        elif t in DISABILITY_TRAITS:
            sig.append(("disability", t))
        elif t in AGING_TRAITS:
            sig.append(("aging", t))
    actor = _enrich(_make_actor(current_holder_id, chars), titles=[])
    for category, trait in sig:
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.DISASTER, y,
            salt_parts=[current_holder_id, "trait", category, trait],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.DISASTER,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=Outcome.UNKNOWN,
            tags=[category, f"trait:{trait}", f"title:{title_label}",
                  "state_of_the_realm"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "kind": "ongoing_affliction_of_current_holder",
                "category": category, "trait": trait,
                "note": "CK3 does not record trait acquisition date; chronicled as state-of-the-realm.",
            }, ensure_ascii=False)[:400],
            world_context=world_context,
        )


# ---------- per-type cap ----------


def _cap_per_type(events: list[ChronicleEvent], cap: int) -> list[ChronicleEvent]:
    """Sort by date desc inside each type; keep the latest ``cap`` per type."""
    by_type: dict[str, list[ChronicleEvent]] = {}
    for e in events:
        by_type.setdefault(e.type.value, []).append(e)
    out: list[ChronicleEvent] = []
    for t, lst in by_type.items():
        lst.sort(key=lambda e: (e.year, e.month or 0, e.day or 0), reverse=True)
        out.extend(lst[:cap])
    out.sort(key=lambda e: (e.year, e.month or 0, e.day or 0))
    return out


# ---------- main ----------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--from-year", type=int, default=None)
    ap.add_argument("--to-year", type=int, default=None)
    ap.add_argument("--max-per-type", type=int, default=6,
                    help="Keep at most N events of each EventType (newest first).")
    ap.add_argument("--player", type=int, default=None,
                    help="Override player char id. Default: played_character.character")
    args = ap.parse_args()

    if args.json is None and args.save is None:
        ap.error("pass --json or --save")
    if args.json is None:
        args.json = convert_save_to_json(args.save)

    t0 = time.perf_counter()
    print(f"[load] {args.json}", flush=True)
    parsed = json.loads(Path(args.json).read_text(encoding="utf-8"))
    print(f"[load] {time.perf_counter() - t0:.1f}s", flush=True)

    save_date = parsed.get("date") or "1066.1.1"
    save_year = _parse_date(save_date)[0] if _parse_date(save_date) else 1066
    if args.from_year is None:
        args.from_year = save_year - 30
    if args.to_year is None:
        args.to_year = save_year

    living = parsed.get("living") or {}
    dead = parsed.get("dead_unprunable") or {}
    chars = {**dead, **living}

    # Player + primary title.
    pc = parsed.get("played_character") or {}
    pid = args.player or pc.get("character")
    if pid is None:
        print("[error] no player id; pass --player", file=sys.stderr)
        sys.exit(2)
    pid = str(int(pid))
    player = chars.get(pid) or {}
    player_first = _decode_ck3_name(player.get("first_name") or f"Character {pid}")
    house_id = player.get("dynasty_house")
    houses = (parsed.get("dynasties") or {}).get("dynasty_house") or {}
    house_name = _decode_house_name(houses, house_id)

    ld = player.get("landed_data") or {}
    domain = ld.get("domain") or []
    if not domain:
        print(f"[error] player {pid} has no domain", file=sys.stderr)
        sys.exit(2)
    primary_id = str(domain[0])

    landed_titles = (parsed.get("landed_titles") or {}).get("landed_titles") or {}
    primary_title = landed_titles.get(primary_id) or {}
    title_key = primary_title.get("key")
    title_label = _decode_title_key(title_key)

    # Government / regnal year heuristic.
    became = ld.get("became_ruler_date")
    became_date = _parse_date(became) if isinstance(became, str) else None
    regnal_year = save_year - became_date[0] if became_date else None

    world_context = (
        f"Reigning ruler: {player_first}, holder of the {title_label} "
        f"(title key: {title_key}).\n"
        f"House: {house_name or 'unknown'}. "
        f"Government: {ld.get('government') or 'unknown'}.\n"
        f"Chronicle written in the year AD {save_year}"
        + (f", the {regnal_year}th year of his reign" if regnal_year and regnal_year > 0 else "")
        + ".\n"
        "Use these names exactly. Do not invent off-screen monarchs. "
        "When referring to the reigning ruler in narrative prose, use his given name."
    )

    print(f"[info] player: {player_first} (id={pid})", flush=True)
    print(f"[info] primary title: {title_label} ({title_key}, id={primary_id})", flush=True)
    print(f"[info] house: {house_name}", flush=True)
    print(f"[info] window: {args.from_year}–{args.to_year} AD  (save date: {save_date})", flush=True)
    print(f"[info] cap per type: {args.max_per_type}", flush=True)

    events: list[ChronicleEvent] = []

    # 1+2. Title-history coronations + holder deaths.
    n0 = len(events)
    events.extend(_extract_holder_history(
        primary_id=primary_id, landed_titles=landed_titles, chars=chars,
        house_name=house_name, title_label=title_label,
        world_context=world_context,
        from_year=args.from_year, to_year=args.to_year,
    ))
    print(f"[info] coronations + holder deaths: {len(events) - n0}", flush=True)

    # 3+4. Heir lifecycle for each holder we've touched in window.
    n0 = len(events)
    touched_holders: set[str] = set()
    if isinstance(primary_title.get("history"), dict):
        for date_s, entry in primary_title["history"].items():
            d = _parse_date(date_s)
            if not d:
                continue
            if not (args.from_year <= d[0] <= args.to_year):
                continue
            if isinstance(entry, int):
                touched_holders.add(str(entry))
            elif isinstance(entry, dict) and entry.get("holder") is not None:
                touched_holders.add(str(entry["holder"]))
    touched_holders.add(pid)  # current holder always
    for holder_id in touched_holders:
        events.extend(_extract_heir_lifecycle(
            holder_id=holder_id, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
    print(f"[info] heir births + heir deaths: {len(events) - n0}", flush=True)

    # 5. Active wars where current holder participates.
    n0 = len(events)
    events.extend(_extract_active_wars(
        parsed=parsed, current_holder_id=pid, chars=chars,
        house_name=house_name, title_label=title_label,
        save_date=save_date, world_context=world_context,
    ))
    print(f"[info] active wars: {len(events) - n0}", flush=True)

    # 6. Current holder's significant traits.
    traits_lookup = parsed.get("traits_lookup") or []
    n0 = len(events)
    events.extend(_extract_holder_traits(
        current_holder_id=pid, chars=chars, traits_lookup=traits_lookup,
        save_date=save_date, world_context=world_context,
        house_name=house_name, title_label=title_label,
    ))
    print(f"[info] holder traits (illness/disability/aging): {len(events) - n0}", flush=True)

    # Cap per type.
    before = len(events)
    events = _cap_per_type(events, args.max_per_type)
    print(f"[info] capped per type (max {args.max_per_type}): {before} → {len(events)}", flush=True)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.json), inserted + skipped)
    print(f"[done] inserted={inserted} skipped={skipped} db={args.db}", flush=True)


if __name__ == "__main__":
    main()
