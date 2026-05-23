"""Dynastic-scope importer — Phase 0.1 / 0.2.

Phase 0.2 adds a player-selectable ``--scope`` flag that broadens (or
narrows) the chronicle's eye on top of the dynastic spine:

  ``dynastic`` (default, Phase 0.1 behaviour)
      Just the primary title's holder line + heirs + wars + traits +
      schemes/stories/artifacts/activities/marriages of the present
      holder. Tight, focused, recommended for landed rulers.

  ``narrow``
      Strip down to the player's own house only: births, deaths, and
      marriages of dynastic-house members in the window. Suitable for
      landless adventurers whose bloodline is the unit, and for landed
      rulers who want a family-album feel.

  ``middle``
      ``narrow`` + ``dynastic``. House-member life events overlaid on
      the primary-title spine. The default sweet spot when in doubt.

  ``wide``
      ``middle`` + every notable landed death in the window (titled
      rulers anywhere in the known world). Capped hard via
      ``--max-per-type`` because saves carry tens of thousands of
      deaths.

Implementation note: rather than three sibling scripts, all scopes flow
through this one driver. ``scripts/import_narrow.py`` and
``scripts/import_real_save.py`` remain as historical prototypes — the
single CLI surface here is what Phase 0.2 ships.

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

from chronicler.parsers.save_import import _make_actor, convert_save_to_json
from chronicler.schema import (
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
from chronicler.scoring import resolve_scope, stamp_era_mood
from chronicler.scoring import significance as _significance
from chronicler.storage import Store

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


def _build_holder_timeline(history: dict) -> list[tuple[tuple[int, int, int], str]]:
    """Walk landed_titles[*].history and return a chronologically sorted list
    of (date, holder_id) tuples. Used to identify who reigned at any given year.
    """
    out: list[tuple[tuple[int, int, int], str]] = []
    if not isinstance(history, dict):
        return out
    for date_s, entry in history.items():
        date = _parse_date(date_s)
        if not date:
            continue
        if isinstance(entry, int):
            holder = entry
        elif isinstance(entry, dict):
            holder = entry.get("holder")
        else:
            continue
        if holder is not None:
            out.append((date, str(holder)))
    out.sort(key=lambda t: t[0])
    return out


def _contemporary_ruler(
    timeline: list[tuple[tuple[int, int, int], str]],
    event_year: int, event_month: int, event_day: int,
    chars: dict,
) -> tuple[str | None, int | None]:
    """Return (decoded_name, regnal_year) for whoever held the primary title
    at the given event date. Returns (None, None) if nothing in the timeline
    precedes the event.
    """
    if not timeline:
        return None, None
    target = (event_year, event_month, event_day)
    holder_id = None
    reign_start: tuple[int, int, int] | None = None
    for date, h in timeline:
        if date <= target:
            holder_id, reign_start = h, date
        else:
            break
    if holder_id is None:
        return None, None
    holder = chars.get(holder_id) or {}
    name = _decode_ck3_name(holder.get("first_name") or f"Character {holder_id}")
    regnal = (event_year - reign_start[0]) + 1 if reign_start else None
    return name, regnal


def _ctx_line_for(event_year: int, event_month: int, event_day: int,
                  timeline, chars) -> str | None:
    name, regnal = _contemporary_ruler(timeline, event_year,
                                       event_month or 1, event_day or 1, chars)
    if not name:
        return None
    if regnal and regnal > 0:
        return (f"At the time of this event the primary title was held by "
                f"{name}, then in the {regnal}{_ordinal_suffix(regnal)} year of his reign.")
    return f"At the time of this event the primary title was held by {name}."


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


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


# ---------- Phase 0.1.1: additional extractors ----------


def _extract_battles(
    *, parsed: dict, holder_ids: set[str], chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
):
    """Past battles from ``combats.combat_results``.

    Each combat is a single tactical engagement (not a whole war). We keep
    the ones where a primary-title holder commanded one of the sides,
    and where the combat actually resolved (``winning_side >= 0`` and
    ``end_date`` not the sentinel ``1.1.1``).
    """
    combats_root = parsed.get("combats") or {}
    combat_results = combats_root.get("combat_results")
    if not isinstance(combat_results, dict):
        return
    for cid, c in combat_results.items():
        if not isinstance(c, dict):
            continue
        end = _parse_date(c.get("end_date"))
        ws = c.get("winning_side")
        # Filter to completed combats only. CK3 stores ongoing engagements
        # in the same table with end_date='1.1.1' and winning_side=-1.
        if not end or end == (1, 1, 1) or (isinstance(ws, int) and ws < 0):
            continue
        start = _parse_date(c.get("start_date")) or end
        y, m, d = start
        if y < from_year or y > to_year:
            continue
        att = c.get("attacker") or {}
        deff = c.get("defender") or {}
        att_cmd = str(att.get("commander")) if isinstance(att, dict) and att.get("commander") else None
        def_cmd = str(deff.get("commander")) if isinstance(deff, dict) and deff.get("commander") else None
        att_main = str(att.get("main_participant")) if isinstance(att, dict) and att.get("main_participant") else None
        def_main = str(deff.get("main_participant")) if isinstance(deff, dict) and deff.get("main_participant") else None
        commanders_and_principals = {x for x in (att_cmd, def_cmd, att_main, def_main) if x}
        if not (commanders_and_principals & holder_ids):
            continue
        # Casualties: starting - surviving on each side.
        def _cas(side):
            if not isinstance(side, dict):
                return None
            init = side.get("inital_soldiers")  # CK3 spells it 'inital'
            surv = side.get("surviving_soldiers")
            if isinstance(init, (int, float)) and isinstance(surv, (int, float)):
                return max(0, int(init) - int(surv))
            return None
        cas = Casualties(
            attacker_dead=_cas(att) if isinstance(att, dict) else None,
            defender_dead=_cas(deff) if isinstance(deff, dict) else None,
        )
        # Pick the holder as primary actor (whichever side they were on).
        anchor = None
        for cand in (att_cmd, def_cmd, att_main, def_main):
            if cand and cand in holder_ids:
                anchor = cand
                break
        if anchor is None:
            continue
        actor = _enrich(_make_actor(anchor, chars))
        # Faction labels.
        factions = []
        for x in (att_cmd, att_main):
            if x:
                factions.append(Faction(
                    name=_decode_ck3_name(_make_actor(x, chars).name),
                    side=FactionSide.ATTACKER,
                ))
                break
        for x in (def_cmd, def_main):
            if x:
                factions.append(Faction(
                    name=_decode_ck3_name(_make_actor(x, chars).name),
                    side=FactionSide.DEFENDER,
                ))
                break
        outcome = Outcome.ATTACKER_VICTORY if ws == 0 else (
            Outcome.DEFENDER_VICTORY if ws == 1 else Outcome.UNKNOWN
        )
        # Did our anchor win?
        anchor_on_attacker = anchor in {att_cmd, att_main}
        anchor_won = (
            (anchor_on_attacker and outcome == Outcome.ATTACKER_VICTORY)
            or (not anchor_on_attacker and outcome == Outcome.DEFENDER_VICTORY)
        )
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.BATTLE, y,
            salt_parts=[str(cid), anchor, str(c.get("location"))],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.BATTLE,
            year=y, month=m, day=d,
            primary_actors=[actor], factions=factions,
            casualties=cas, outcome=outcome,
            tags=[f"province:{c.get('location')}",
                  ("victory" if anchor_won else "defeat"),
                  ("attacker" if anchor_on_attacker else "defender"),
                  f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "location_province": c.get("location"),
                "end_date": c.get("end_date"),
                "attacker_initial": att.get("inital_soldiers") if isinstance(att, dict) else None,
                "attacker_surviving": att.get("surviving_soldiers") if isinstance(att, dict) else None,
                "defender_initial": deff.get("inital_soldiers") if isinstance(deff, dict) else None,
                "defender_surviving": deff.get("surviving_soldiers") if isinstance(deff, dict) else None,
            }, ensure_ascii=False)[:500],
            world_context=world_context,
        )


def _extract_player_schemes(
    *, parsed: dict, current_holder_id: str, chars: dict,
    house_name: str | None, title_label: str,
    world_context: str,
):
    """Schemes the reigning ruler is actively running (or that target him).

    Schemes are still in flight — the chronicler records them as palace
    intrigue (own scheme) or as a perceived threat (targeting scheme).
    """
    schemes_active = ((parsed.get("schemes") or {}).get("active")) or {}
    holder = chars.get(current_holder_id) or {}
    ad = holder.get("alive_data") or {}
    own = ad.get("schemes") or []
    targeting = ad.get("targeting_schemes") or []
    for sid, role in [(s, "owner") for s in own] + [(s, "target") for s in targeting]:
        s = schemes_active.get(str(sid))
        if not isinstance(s, dict):
            continue
        scheme_type = s.get("type") or "scheme"
        date = _parse_date(s.get("date"))
        if not date:
            continue
        y, m, d = date
        owner_id = str(s.get("owner") or current_holder_id)
        target = s.get("target")
        target_id = None
        if isinstance(target, dict) and target.get("target") is not None:
            target_id = str(target["target"])
        # Treat "ongoing" as a scheme_active marker (chronicler can frame it
        # as palace intrigue without claiming an outcome).
        anchor_id = current_holder_id
        actor = _enrich(_make_actor(anchor_id, chars))
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.SCHEME_ACTIVE, y,
            salt_parts=[str(sid), scheme_type, owner_id, target_id or "no_target"],
        )
        target_name = (
            _decode_ck3_name(_make_actor(target_id, chars).name)
            if target_id and chars.get(target_id) else None
        )
        owner_name = (
            _decode_ck3_name(_make_actor(owner_id, chars).name)
            if owner_id and chars.get(owner_id) else None
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.SCHEME_ACTIVE,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=Outcome.UNKNOWN,
            tags=["ongoing", f"scheme:{scheme_type}", f"role:{role}",
                  f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "scheme_type": scheme_type,
                "role": role,
                "owner_name": owner_name,
                "target_name": target_name,
                "progress": s.get("progress"),
                "secrecy": s.get("secrecy"),
            }, ensure_ascii=False)[:400],
            world_context=world_context,
        )


def _extract_player_stories(
    *, parsed: dict, current_holder_id: str, chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
):
    """Active CK3 stories whose ``owner`` is the reigning ruler.

    Stories track multi-step arcs (pet dog, journey, vassal feud, etc.).
    Each is anchored at its first listed date.
    """
    stories = ((parsed.get("stories") or {}).get("active")) or {}
    if not isinstance(stories, dict):
        return
    for sid, s in stories.items():
        if not isinstance(s, dict):
            continue
        if str(s.get("owner") or "") != current_holder_id:
            continue
        dates = s.get("dates") or []
        date = _parse_date(dates[0]) if isinstance(dates, list) and dates else None
        if not date:
            continue
        y, m, d = date
        if y < from_year or y > to_year:
            continue
        cycle = s.get("story_cycle") or "story"
        # Flatten variable flags for the brief.
        var_flags: list[str] = []
        v = s.get("variables") or {}
        if isinstance(v, dict):
            for d_ in (v.get("data") or []):
                if isinstance(d_, dict):
                    flag = d_.get("flag")
                    payload = d_.get("data") or {}
                    if isinstance(payload, dict):
                        var_flags.append(f"{flag}={payload.get('flag', payload.get('identity', '?'))}")
        actor = _enrich(_make_actor(current_holder_id, chars))
        eid = make_event_id(
            Source.SAVE_IMPORT, EventType.STORY_EVENT, y,
            salt_parts=[str(sid), cycle, current_holder_id],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=EventType.STORY_EVENT,
            year=y, month=m, day=d,
            primary_actors=[actor], outcome=Outcome.UNKNOWN,
            tags=[f"story:{cycle}", f"title:{title_label}"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "story_cycle": cycle,
                "variables": var_flags,
                "all_dates": dates,
            }, ensure_ascii=False)[:500],
            world_context=world_context,
        )


def _extract_artifacts(
    *, parsed: dict, holder_ids: set[str], chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
    max_artifacts: int = 8,
):
    """Artifact acquisitions touching a primary-title holder.

    Walks ``artifacts.artifacts``; for each artifact whose history mentions
    a holder_id as recipient (inherited/purchased/gifted/looted), emits
    the acquisition event. Capped early because saves can carry 6000+
    artifacts.
    """
    arts = ((parsed.get("artifacts") or {}).get("artifacts")) or {}
    if not isinstance(arts, dict):
        return
    emitted = 0
    interesting_types = {"inherited", "purchased", "gifted", "looted",
                         "created", "claimed", "stolen"}
    for aid, a in arts.items():
        if emitted >= max_artifacts:
            return
        if not isinstance(a, dict):
            continue
        hist = (a.get("history") or {}).get("entries") if isinstance(a.get("history"), dict) else None
        if not isinstance(hist, list):
            continue
        for entry in hist:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            if entry_type not in interesting_types:
                continue
            recipient = entry.get("recipient")
            if recipient is None or str(recipient) not in holder_ids:
                continue
            date = _parse_date(entry.get("date"))
            if not date:
                continue
            y, m, d = date
            if y < from_year or y > to_year:
                continue
            actor = _enrich(_make_actor(str(recipient), chars))
            art_name = a.get("name") or "an unnamed object"
            art_type = a.get("type") or "artifact"
            rarity = a.get("rarity") or "common"
            eid = make_event_id(
                Source.SAVE_IMPORT, EventType.ARTIFACT_ACQUIRED, y,
                salt_parts=[str(aid), entry_type, str(recipient), str(y)],
            )
            yield ChronicleEvent(
                event_id=eid, source=Source.SAVE_IMPORT, type=EventType.ARTIFACT_ACQUIRED,
                year=y, month=m, day=d,
                primary_actors=[actor], outcome=Outcome.SUCCESS,
                tags=[entry_type, f"rarity:{rarity}", f"artifact_type:{art_type}",
                      f"title:{title_label}"]
                     + ([f"house:{house_name}"] if house_name else []),
                raw_excerpt=json.dumps({
                    "artifact_name": art_name,
                    "artifact_type": art_type,
                    "rarity": rarity,
                    "acquisition_mode": entry_type,
                    "description": (a.get("description") or "")[:300],
                }, ensure_ascii=False)[:700],
                world_context=world_context,
            )
            emitted += 1
            break  # one acquisition event per artifact


def _extract_activities(
    *, parsed: dict, current_holder_id: str, chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
    reign_start_year: int | None = None,
):
    """Activities the reigning ruler has hosted or attended.

    CK3 keeps ``last_open_activity_dates`` and ``last_hosted_activity_dates``
    in ``played_character`` — one date per activity type, most recent
    occurrence. We trust ``last_hosted`` (those are the player's own).
    ``last_open`` entries dated before the player's accession are stale
    CK3 cruft (initialized from predecessors) and are dropped — otherwise
    the chronicle ends up claiming the present ruler attended events
    decades before they were born.
    """
    pc = parsed.get("played_character") or {}
    raw_sections = [
        ("hosted", pc.get("last_hosted_activity_dates") or {}, False),
        ("attended", pc.get("last_open_activity_dates") or {}, True),
    ]
    sections = []
    for role, table, drop_pre_reign in raw_sections:
        if not isinstance(table, dict):
            continue
        if drop_pre_reign and reign_start_year is not None:
            table = {k: v for k, v in table.items()
                     if (_parse_date(v) or (0, 0, 0))[0] >= reign_start_year}
        sections.append((role, table))
    for role, table in sections:
        if not isinstance(table, dict):
            continue
        for activity_type, date_s in (table.items() if isinstance(table, dict) else []):
            date = _parse_date(date_s)
            if not date:
                continue
            y, m, d = date
            if y < from_year or y > to_year:
                continue
            actor = _enrich(_make_actor(current_holder_id, chars))
            # Pretty label: 'activity_imperial_examination' → 'imperial_examination'
            pretty = activity_type
            if isinstance(activity_type, str) and activity_type.startswith("activity_"):
                pretty = activity_type[len("activity_"):]
            eid = make_event_id(
                Source.SAVE_IMPORT, EventType.ACTIVITY, y,
                salt_parts=[current_holder_id, role, activity_type, str(y), str(m), str(d)],
            )
            yield ChronicleEvent(
                event_id=eid, source=Source.SAVE_IMPORT, type=EventType.ACTIVITY,
                year=y, month=m, day=d,
                primary_actors=[actor], outcome=Outcome.SUCCESS,
                tags=[f"activity:{pretty}", f"role:{role}",
                      f"title:{title_label}"]
                     + ([f"house:{house_name}"] if house_name else []),
                raw_excerpt=json.dumps({
                    "activity_type": activity_type,
                    "role": role,
                    "note": "Dated to the most recent occurrence; CK3 only stores latest per type.",
                }, ensure_ascii=False)[:300],
                world_context=world_context,
            )


def _extract_marriages(
    *, parsed: dict, current_holder_id: str, chars: dict,
    house_name: str | None, title_label: str,
    world_context: str, from_year: int, to_year: int,
):
    """Marriage events for the reigning holder + their listed predecessors.

    ``family_data`` carries spouse character ids but no date. We approximate
    by taking the holder's first child's birth date and subtracting one year
    (a reasonable medieval anchor: a child within the first year of marriage
    is typical). Where no children exist we fall back to the holder's own
    accession date.

    We only emit marriages where we can find a credible anchor date.
    """
    # The holders we care about: current + any in the primary title's history
    # is already collected by the caller and passed via current_holder_id.
    # For this extractor we'll just do the current holder and primary spouse.
    holder = chars.get(current_holder_id) or {}
    fd = holder.get("family_data") or {}
    spouse_id = fd.get("primary_spouse") or fd.get("spouse")
    if spouse_id is None:
        return
    spouse_id = str(spouse_id)
    if not chars.get(spouse_id):
        return
    # Anchor date: eldest child's birth minus one year, else accession.
    anchor: tuple[int, int, int] | None = None
    for cid in fd.get("child") or []:
        c = chars.get(str(cid))
        if isinstance(c, dict):
            b = _parse_date(c.get("birth"))
            if b and (anchor is None or b < anchor):
                anchor = b
    if anchor is not None:
        # Subtract a year-ish, clamp to month 1.
        ay, am, ad_ = anchor
        anchor = (max(1, ay - 1), 1, 1)
    if anchor is None:
        ld = holder.get("landed_data") or {}
        anchor = _parse_date(ld.get("became_ruler_date"))
    if anchor is None:
        return
    y, m, d = anchor
    if y < from_year or y > to_year:
        return
    actor = _enrich(_make_actor(current_holder_id, chars))
    spouse_actor = _enrich(_make_actor(spouse_id, chars))
    eid = make_event_id(
        Source.SAVE_IMPORT, EventType.MARRIAGE, y,
        salt_parts=[current_holder_id, spouse_id, str(y)],
    )
    yield ChronicleEvent(
        event_id=eid, source=Source.SAVE_IMPORT, type=EventType.MARRIAGE,
        year=y, month=m, day=d,
        primary_actors=[actor, spouse_actor], outcome=Outcome.SUCCESS,
        tags=["primary_spouse", f"title:{title_label}"]
             + ([f"house:{house_name}"] if house_name else []),
        raw_excerpt=json.dumps({
            "anchor_method": "first_child_birth_minus_one_year",
            "spouse_name": spouse_actor.name,
            "note": "CK3 saves don't store marriage dates directly; this anchor is approximate.",
        }, ensure_ascii=False)[:400],
        world_context=world_context,
    )


# ---------- Phase 0.2: scope-widening extractors ----------


def _extract_house_lifecycle(
    *, chars: dict, house_id, house_name: str | None,
    world_context: str, from_year: int, to_year: int,
):
    """Births + deaths of every dynastic-house member within window.

    Powers ``--scope narrow`` (the family-album view) and is also folded
    into ``middle`` and ``wide`` on top of the dynastic spine.
    """
    if house_id is None:
        return
    for cid, c in chars.items():
        if not isinstance(c, dict):
            continue
        if c.get("dynasty_house") != house_id:
            continue
        # Birth.
        b = _parse_date(c.get("birth"))
        if b and from_year <= b[0] <= to_year:
            y, m, d = b
            actor = _enrich(_make_actor(str(cid), chars))
            eid = make_event_id(
                Source.SAVE_IMPORT, EventType.BIRTH, y,
                salt_parts=[str(cid), "house_birth", str(y)],
            )
            yield ChronicleEvent(
                event_id=eid, source=Source.SAVE_IMPORT, type=EventType.BIRTH,
                year=y, month=m, day=d,
                primary_actors=[actor], outcome=Outcome.SUCCESS,
                tags=["house_member"] + ([f"house:{house_name}"] if house_name else []),
                raw_excerpt=json.dumps({
                    "relation_to_player": "house_member",
                    "house": house_name,
                }, ensure_ascii=False)[:300],
                world_context=world_context,
            )
        # Death.
        dd = c.get("dead_data") or {}
        if not isinstance(dd, dict):
            continue
        date = _parse_date(dd.get("date"))
        if not date:
            continue
        y, m, d = date
        if y < from_year or y > to_year:
            continue
        reason = str(dd.get("reason") or "")
        is_murder = (
            reason in MURDER_REASONS or "murder" in reason or "assassin" in reason
        )
        et = EventType.MURDER if is_murder else EventType.RULER_DEATH
        actor = _enrich(
            _make_actor(str(cid), chars),
            titles=dd.get("domain") if isinstance(dd.get("domain"), list) else [],
        )
        eid = make_event_id(
            Source.SAVE_IMPORT, et, y,
            salt_parts=[str(cid), "house_death", reason, str(y)],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=et,
            year=y, month=m, day=d,
            primary_actors=[actor],
            outcome=Outcome.FAILURE if is_murder else Outcome.NATURAL,
            tags=["house_member", reason or "unknown_cause"]
                 + ([f"house:{house_name}"] if house_name else []),
            raw_excerpt=json.dumps({
                "dead_data": dd, "relation_to_player": "house_member",
                "house": house_name,
            }, ensure_ascii=False)[:600],
            world_context=world_context,
        )


def _extract_notable_landed_deaths(
    *, chars: dict, world_context: str, from_year: int, to_year: int,
    exclude_ids: set[str], max_events: int,
):
    """Every titled ruler's death anywhere in the known world.

    Powers ``--scope wide``. ``exclude_ids`` skips characters already
    surfaced by other extractors. Capped early — saves carry 90k+ dead
    NPCs; only landed/titled ones with a death cause make the cut.
    """
    out: list[ChronicleEvent] = []
    for cid, c in chars.items():
        if str(cid) in exclude_ids:
            continue
        if not isinstance(c, dict):
            continue
        dd = c.get("dead_data") or {}
        if not isinstance(dd, dict):
            continue
        reason = dd.get("reason")
        if not reason:
            continue
        if not (dd.get("domain") or dd.get("liege_title")):
            continue
        date = _parse_date(dd.get("date"))
        if not date:
            continue
        y, m, d = date
        if y < from_year or y > to_year:
            continue
        out.append((date, cid, c, str(reason), dd))
    # Keep the latest N (closest to the save's present).
    out.sort(key=lambda t: t[0])
    out = out[-max_events:]
    for date, cid, _c, reason, dd in out:
        y, m, d = date
        is_murder = (
            reason in MURDER_REASONS or "murder" in reason or "assassin" in reason
        )
        et = EventType.MURDER if is_murder else EventType.RULER_DEATH
        actor = _enrich(
            _make_actor(str(cid), chars),
            titles=dd.get("domain") if isinstance(dd.get("domain"), list) else [],
        )
        eid = make_event_id(
            Source.SAVE_IMPORT, et, y,
            salt_parts=[str(cid), "notable_death", reason, str(y)],
        )
        yield ChronicleEvent(
            event_id=eid, source=Source.SAVE_IMPORT, type=et,
            year=y, month=m, day=d,
            primary_actors=[actor],
            outcome=Outcome.FAILURE if is_murder else Outcome.NATURAL,
            tags=["notable_ruler", reason or "unknown_cause"],
            raw_excerpt=json.dumps({
                "dead_data": dd, "relation_to_player": "foreign_ruler",
            }, ensure_ascii=False)[:600],
            world_context=world_context,
        )


# ---------- Phase 0.3: era-mood stamping ----------

# (DARK_EVENT_TYPES + _stamp_era_mood moved to chronicler.scoring in
# Phase 0.5 so the function gets direct test coverage. The importer
# calls ``stamp_era_mood`` from there.)


# ---------- Phase 0.3: significance-based selection ----------
# (SIGNIFICANCE table + scoring helper moved to chronicler.scoring in
# Phase 0.4 so the live-hook watcher can apply the same ranking.)


def _select_events(
    events: list[ChronicleEvent],
    *,
    max_total: int,
    max_per_type: int,
) -> list[ChronicleEvent]:
    """Two-stage trim: per-type cap first (so one category can't drown
    the chronicle), then global cap by significance (so the surviving set
    is meaningful, not just recent)."""
    capped = _cap_per_type(events, max_per_type)
    if len(capped) <= max_total:
        return sorted(
            capped, key=lambda e: (e.year, e.month or 0, e.day or 0)
        )
    # Rank by (significance desc, year desc, month desc, day desc).
    ranked = sorted(
        capped,
        key=lambda e: (
            -_significance(e),
            -e.year,
            -(e.month or 0),
            -(e.day or 0),
        ),
    )
    kept = ranked[:max_total]
    return sorted(kept, key=lambda e: (e.year, e.month or 0, e.day or 0))


# ---------- per-type cap ----------


def _cap_per_type(events: list[ChronicleEvent], cap: int) -> list[ChronicleEvent]:
    """Sort by date desc inside each type; keep the latest ``cap`` per type."""
    by_type: dict[str, list[ChronicleEvent]] = {}
    for e in events:
        by_type.setdefault(e.type.value, []).append(e)
    out: list[ChronicleEvent] = []
    for _t, lst in by_type.items():
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
    ap.add_argument("--max-per-type", type=int, default=None,
                    help="Per-EventType cap (newest first). Default comes from "
                         "the scope preset: narrow=2, dynastic/middle=3, wide=5.")
    ap.add_argument("--max-events", type=int, default=None,
                    help="Global cap. After per-type trimming, keep the top N "
                         "by significance score. Default from scope preset: "
                         "narrow=6, dynastic/middle=12, wide=24.")
    ap.add_argument("--max-artifacts", type=int, default=4,
                    help="Hard cap on artifact extractor (saves can hold 6000+).")
    ap.add_argument("--player", type=int, default=None,
                    help="Override player char id. Default: played_character.character")
    ap.add_argument(
        "--scope",
        choices=["dynastic", "narrow", "middle", "wide"],
        default="dynastic",
        help=(
            "How wide the chronicle's eye should be — and how strict the "
            "cutoff. Each preset bundles a scope and a strictness profile: "
            "narrow = house only, very strict (≤6 events). "
            "dynastic = primary-title spine, medium (Phase 0.3 default, ≤12). "
            "middle = narrow + dynastic, medium (≤12). "
            "wide = middle + every notable landed death, looser (≤24). "
            "Override the strictness via --max-per-type / --max-events."
        ),
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
    # regnal_year retained inline in print/log below if needed; not used here.

    world_context = (
        f"This volume of the chronicle is presently being compiled at the court of "
        f"{player_first}, who in {save_year} AD holds the {title_label} "
        f"(title key: {title_key}, house {house_name or 'unknown'}, government "
        f"{ld.get('government') or 'unknown'}). The compiler writes in {save_year} AD.\n"
        "Each entry below has its OWN date in the EVENT block. The entry must be "
        "narrated as something that happened in THAT year, with the reigning monarch "
        "OF THAT YEAR. If the event predates the present compiler's reign by decades "
        f"or centuries, do NOT mention {player_first} in the entry, and do NOT cite "
        f"{player_first}'s regnal year — refer to whoever the brief identifies as the "
        "actor or the 'contemporary_ruler'.\n"
        "Use names exactly as given. Do not invent off-screen monarchs."
    )

    print(f"[info] player: {player_first} (id={pid})", flush=True)
    print(f"[info] primary title: {title_label} ({title_key}, id={primary_id})", flush=True)
    print(f"[info] house: {house_name}", flush=True)
    print(f"[info] window: {args.from_year}–{args.to_year} AD  (save date: {save_date})", flush=True)
    # Phase 0.4: resolve --scope → strictness preset, then apply any CLI
    # overrides. The preset bundles (max_per_type, max_events) so the
    # player has one knob in the common case.
    preset = resolve_scope(args.scope)
    if args.max_per_type is None:
        args.max_per_type = preset.max_per_type or 3
    if args.max_events is None:
        args.max_events = preset.max_events or 12
    print(
        f"[info] scope={args.scope} preset(max_per_type={preset.max_per_type}, "
        f"max_events={preset.max_events}) → effective "
        f"(max_per_type={args.max_per_type}, max_events={args.max_events})",
        flush=True,
    )

    # Scope flags. ``dynastic`` is the Phase 0.1 default — primary-title
    # spine. ``narrow`` strips that down to the player's house alone.
    # ``middle`` overlays both. ``wide`` further pulls notable foreign
    # deaths for a world-scale chronicle.
    do_dynastic = args.scope in {"dynastic", "middle", "wide"}
    do_house = args.scope in {"narrow", "middle", "wide"}
    do_world = args.scope == "wide"

    events: list[ChronicleEvent] = []

    if not do_dynastic:
        # Narrow still needs the contemporary-ruler timeline so dates
        # have a regnal anchor, but skips emitting the spine events.
        pass

    # 1+2. Title-history coronations + holder deaths.
    n0 = len(events)
    if do_dynastic:
        events.extend(_extract_holder_history(
            primary_id=primary_id, landed_titles=landed_titles, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
        print(f"[info] coronations + holder deaths: {len(events) - n0}", flush=True)

    # 3+4. Heir lifecycle for each holder we've touched in window.
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
    if do_dynastic:
        n0 = len(events)
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

        # 7. Past battles commanded by any holder in our touched set.
        n0 = len(events)
        events.extend(_extract_battles(
            parsed=parsed, holder_ids=touched_holders, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
        print(f"[info] past battles: {len(events) - n0}", flush=True)

        # 8. Active schemes (player as owner or target).
        n0 = len(events)
        events.extend(_extract_player_schemes(
            parsed=parsed, current_holder_id=pid, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
        ))
        print(f"[info] active schemes: {len(events) - n0}", flush=True)

        # 9. Active stories owned by the reigning ruler.
        n0 = len(events)
        events.extend(_extract_player_stories(
            parsed=parsed, current_holder_id=pid, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
        print(f"[info] stories: {len(events) - n0}", flush=True)

        # 10. Artifacts acquired by any holder in our touched set.
        n0 = len(events)
        events.extend(_extract_artifacts(
            parsed=parsed, holder_ids=touched_holders, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
            max_artifacts=args.max_artifacts,
        ))
        print(f"[info] artifacts: {len(events) - n0}", flush=True)

        # 11. Activities hosted / attended by the reigning ruler.
        n0 = len(events)
        events.extend(_extract_activities(
            parsed=parsed, current_holder_id=pid, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
            reign_start_year=became_date[0] if became_date else None,
        ))
        print(f"[info] activities: {len(events) - n0}", flush=True)

        # 12. Approximate marriage event for the current holder.
        n0 = len(events)
        events.extend(_extract_marriages(
            parsed=parsed, current_holder_id=pid, chars=chars,
            house_name=house_name, title_label=title_label,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
        print(f"[info] marriages: {len(events) - n0}", flush=True)

    # 13. (Phase 0.2) House lifecycle — narrow / middle / wide.
    if do_house:
        n0 = len(events)
        events.extend(_extract_house_lifecycle(
            chars=chars, house_id=house_id, house_name=house_name,
            world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
        ))
        print(f"[info] house lifecycle (births+deaths): {len(events) - n0}", flush=True)

    # 14. (Phase 0.2) Notable foreign rulers' deaths — wide only.
    if do_world:
        already = {a.character_id for ev in events for a in ev.primary_actors}
        n0 = len(events)
        events.extend(_extract_notable_landed_deaths(
            chars=chars, world_context=world_context,
            from_year=args.from_year, to_year=args.to_year,
            exclude_ids=already,
            # Honour the per-type cap so wide doesn't drown narrow.
            max_events=max(args.max_per_type * 2, 10),
        ))
        print(f"[info] notable foreign deaths: {len(events) - n0}", flush=True)

    # Per-event contemporary-ruler anchor. CK3's "Nth year of his reign"
    # phrasing is meaningful only with this stamped per event; without it
    # the LLM falls back on the compiler's regnal year for everything.
    timeline = _build_holder_timeline(primary_title.get("history") or {})
    for ev in events:
        line = _ctx_line_for(ev.year, ev.month or 1, ev.day or 1, timeline, chars)
        if line:
            ev.contemporary_ruler = line
    print(f"[info] contemporary-ruler timeline: {len(timeline)} reign-changes seen", flush=True)

    # Phase 0.3: significance-based selection. First trim by per-type
    # cap (so no single category drowns the chronicle), then keep the
    # top --max-events by significance score. This replaces the old
    # "newest N per type" naive cap.
    before = len(events)
    events = _select_events(
        events,
        max_total=args.max_events,
        max_per_type=args.max_per_type,
    )
    print(
        f"[info] selected (max_per_type={args.max_per_type}, "
        f"max_events={args.max_events}): {before} → {len(events)}",
        flush=True,
    )

    # Phase 0.3: era-mood stamping. Has to come AFTER selection so the
    # mean is computed against the events the player will actually read,
    # not against all the raw candidates.
    stamp_era_mood(events)
    moods = {}
    for e in events:
        if e.era_mood:
            moods[e.era_mood] = moods.get(e.era_mood, 0) + 1
    if moods:
        print(f"[info] era moods: {moods}", flush=True)

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.json), inserted + skipped)
    print(f"[done] inserted={inserted} skipped={skipped} db={args.db}", flush=True)


if __name__ == "__main__":
    main()
