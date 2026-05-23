"""CK3 save-file importer.

Strategy
--------
CK3 save files come in three forms (uncompressed text, zipped, ironman binary).
We delegate decoding to `rakaly` (https://github.com/rakaly), which already
handles all three and produces JSON.

Pipeline:
    save.ck3  --[rakaly json]-->  parsed_save.json  --[extract]-->  [ChronicleEvent, ...]

If `rakaly` is not on PATH, callers can use `parse_save_json()` directly on
an already-converted JSON file. Tests use fixture JSON to avoid the dependency.

Schema note
-----------
The rakaly JSON layout for CK3 is large and partly undocumented. We extract
defensively: present keys are used, absent keys produce no event. The parser
is intentionally tolerant — it should never raise on unfamiliar shapes;
instead it logs a warning and skips.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..schema import (
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

log = logging.getLogger(__name__)


class RakalyNotFoundError(RuntimeError):
    """Raised when rakaly is required but not installed on PATH."""


def _project_root_bin() -> Path | None:
    """Look upward from this file for a sibling ``bin/`` directory.

    Lets the project ship a pinned rakaly without touching system PATH.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "bin"
        if cand.is_dir():
            return cand
    return None


def _rakaly_path() -> str | None:
    """Find rakaly. Precedence: $CHRONICLER_RAKALY → project bin/ → PATH."""
    env = os.environ.get("CHRONICLER_RAKALY")
    if env and Path(env).exists():
        return env
    binroot = _project_root_bin()
    if binroot:
        for name in ("rakaly.exe", "rakaly"):
            cand = binroot / name
            if cand.exists():
                return str(cand)
    onpath = shutil.which("rakaly")
    return onpath


def rakaly_available() -> bool:
    return _rakaly_path() is not None


def convert_save_to_json(save_path: str | Path, out_path: str | Path | None = None) -> Path:
    """Invoke rakaly to convert a .ck3 save into JSON.

    Returns the path to the resulting JSON file. If `out_path` is omitted,
    writes alongside the save with a `.json` suffix.
    """
    exe = _rakaly_path()
    if not exe:
        raise RakalyNotFoundError(
            "rakaly CLI not found. Set $CHRONICLER_RAKALY, drop the binary in "
            "<repo>/bin/, install it on PATH, or supply a pre-converted JSON "
            "to parse_save_json()."
        )
    save_path = Path(save_path)
    out_path = Path(out_path) if out_path else save_path.with_suffix(".json")
    log.info("Converting %s via %s ...", save_path, exe)
    with out_path.open("wb") as f:
        proc = subprocess.run(
            [exe, "json", str(save_path)],
            stdout=f,
            stderr=subprocess.PIPE,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"rakaly failed (code {proc.returncode}): {proc.stderr.decode(errors='replace')}"
        )
    return out_path


def parse_save(save_path: str | Path) -> dict:
    """Full pipeline: convert .ck3 to JSON then load. Requires rakaly."""
    json_path = convert_save_to_json(save_path)
    return parse_save_json(json_path)


def parse_save_json(json_path: str | Path) -> dict:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def extract_events(parsed: dict) -> Iterator[ChronicleEvent]:
    """Yield ChronicleEvents from a rakaly-parsed save tree.

    Currently extracts:
    - ruler_death / murder from dead_unprunable
    - war_end from wars / past_wars
    - coronation from title_history
    - marriage from living characters' family_data
    """
    chars = _index_characters(parsed)
    yield from _extract_deaths(parsed, chars)
    yield from _extract_wars(parsed, chars)
    yield from _extract_coronations(parsed, chars)
    yield from _extract_marriages(parsed, chars)


# ---------- character index ----------


def _index_characters(parsed: dict) -> dict[str, dict]:
    """Build {character_id: raw_character_dict} from living + dead sections."""
    out: dict[str, dict] = {}
    for section in ("living", "dead_unprunable", "dead_prunable", "characters"):
        sect = _get(parsed, section)
        if isinstance(sect, dict):
            for cid, cdata in sect.items():
                if isinstance(cdata, dict):
                    out[str(cid)] = cdata
    # rakaly sometimes nests under "character_manager" → "database"
    cm = _get(parsed, "character_manager", "database") or _get(parsed, "characters", "database")
    if isinstance(cm, dict):
        for cid, cdata in cm.items():
            if isinstance(cdata, dict):
                out[str(cid)] = cdata
    return out


def _make_actor(char_id: str, chars: dict[str, dict]) -> Actor:
    raw = chars.get(str(char_id), {})
    name = raw.get("first_name") or raw.get("name") or f"Character {char_id}"
    if isinstance(name, dict):
        name = name.get("key", str(name))
    return Actor(
        character_id=str(char_id),
        name=str(name),
        dynasty=_strify(raw.get("dynasty_house") or raw.get("dynasty")),
        culture=_strify(raw.get("culture")),
        religion=_strify(raw.get("faith") or raw.get("religion")),
        titles=[str(t) for t in _aslist(raw.get("landed_data", {}).get("domain") if isinstance(raw.get("landed_data"), dict) else None)],
        traits=[str(t) for t in _aslist(raw.get("traits"))],
        age_at_event=_safe_int(raw.get("age")),
    )


# ---------- extractors ----------


def _extract_deaths(parsed: dict, chars: dict[str, dict]) -> Iterator[ChronicleEvent]:
    dead = _get(parsed, "dead_unprunable")
    if not isinstance(dead, dict):
        return
    for cid, cdata in dead.items():
        if not isinstance(cdata, dict):
            continue
        death = cdata.get("dead_data") or cdata.get("death") or {}
        if not isinstance(death, dict):
            continue
        date = _parse_date(death.get("date") or cdata.get("date"))
        if not date:
            continue
        year, month, day = date
        reason = _strify(death.get("reason") or death.get("death_reason") or "natural")
        is_murder = "murder" in (reason or "").lower() or "assassin" in (reason or "").lower()
        actor = _make_actor(cid, chars)
        event_type = EventType.MURDER if is_murder else EventType.RULER_DEATH
        outcome = Outcome.FAILURE if is_murder else Outcome.NATURAL
        # Only chronicle deaths of characters who held a title (rulers).
        # Phase 0 keeps it broad: include any death with a reason.
        eid = make_event_id(
            Source.SAVE_IMPORT, event_type, year, salt_parts=[str(cid), reason or ""]
        )
        yield ChronicleEvent(
            event_id=eid,
            source=Source.SAVE_IMPORT,
            type=event_type,
            year=year,
            month=month,
            day=day,
            primary_actors=[actor],
            outcome=outcome,
            tags=[reason] if reason else [],
            raw_excerpt=json.dumps({"death": death})[:500],
        )


def _extract_wars(parsed: dict, chars: dict[str, dict]) -> Iterator[ChronicleEvent]:
    # "wars" holds active wars; ended wars are typically in "past_wars"
    # or attached to characters. We probe both.
    for key in ("past_wars", "wars"):
        section = _get(parsed, key)
        if not isinstance(section, (dict, list)):
            continue
        items = section.values() if isinstance(section, dict) else section
        for war in items:
            if not isinstance(war, dict):
                continue
            end_date = _parse_date(war.get("end_date") or war.get("date_end") or war.get("end"))
            start_date = _parse_date(war.get("start_date") or war.get("date_start"))
            if not end_date:
                # Active war — skip in Phase 0 (we chronicle resolved events).
                continue
            year, month, day = end_date
            attackers = _aslist(war.get("attackers") or war.get("attacker") or war.get("attacker_side"))
            defenders = _aslist(war.get("defenders") or war.get("defender") or war.get("defender_side"))
            primary_actors: list[Actor] = []
            for cid in (attackers + defenders)[:2]:
                primary_actors.append(_make_actor(str(cid), chars))
            if not primary_actors:
                primary_actors = [Actor(character_id="unknown", name="An unnamed claimant")]
            factions = []
            for cid in attackers:
                factions.append(Faction(name=_make_actor(str(cid), chars).name, side=FactionSide.ATTACKER))
            for cid in defenders:
                factions.append(Faction(name=_make_actor(str(cid), chars).name, side=FactionSide.DEFENDER))
            winner = _strify(war.get("winner") or war.get("victor"))
            if winner == "attacker":
                outcome = Outcome.ATTACKER_VICTORY
            elif winner == "defender":
                outcome = Outcome.DEFENDER_VICTORY
            else:
                outcome = Outcome.WHITE_PEACE
            name = _strify(war.get("name") or war.get("war_name")) or "an unnamed war"
            cas = war.get("casualties") if isinstance(war.get("casualties"), dict) else {}
            casualties = Casualties(
                attacker_dead=_safe_int(cas.get("attacker")),
                defender_dead=_safe_int(cas.get("defender")),
            )
            eid = make_event_id(
                Source.SAVE_IMPORT,
                EventType.WAR_END,
                year,
                salt_parts=[name, str(start_date), str(end_date), ",".join(attackers), ",".join(defenders)],
            )
            yield ChronicleEvent(
                event_id=eid,
                source=Source.SAVE_IMPORT,
                type=EventType.WAR_END,
                year=year,
                month=month,
                day=day,
                primary_actors=primary_actors,
                factions=factions,
                casualties=casualties,
                outcome=outcome,
                tags=[name] if name else [],
                raw_excerpt=json.dumps({"war_name": name, "winner": winner})[:500],
            )


def _extract_coronations(parsed: dict, chars: dict[str, dict]) -> Iterator[ChronicleEvent]:
    """Emit coronation events from title_history.holder transitions."""
    th = _get(parsed, "title_history") or _get(parsed, "titles", "history")
    if not isinstance(th, dict):
        return
    for title_id, history in th.items():
        entries = _aslist(history if isinstance(history, list) else history.get("history") if isinstance(history, dict) else None)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            evt_type = _strify(entry.get("type") or entry.get("event"))
            if evt_type not in ("inherited", "claimed", "elected", "usurped", "created", "granted"):
                continue
            date = _parse_date(entry.get("date"))
            if not date:
                continue
            year, month, day = date
            holder = _strify(entry.get("holder") or entry.get("character"))
            if not holder:
                continue
            actor = _make_actor(holder, chars)
            event_type = (
                EventType.TITLE_CREATION
                if evt_type == "created"
                else EventType.CORONATION
            )
            eid = make_event_id(
                Source.SAVE_IMPORT,
                event_type,
                year,
                salt_parts=[str(title_id), holder, evt_type],
            )
            yield ChronicleEvent(
                event_id=eid,
                source=Source.SAVE_IMPORT,
                type=event_type,
                year=year,
                month=month,
                day=day,
                primary_actors=[actor],
                outcome=Outcome.SUCCESS,
                tags=[evt_type, str(title_id)],
                raw_excerpt=json.dumps(entry)[:500],
            )


def _extract_marriages(parsed: dict, chars: dict[str, dict]) -> Iterator[ChronicleEvent]:
    """Emit marriage events. Phase 0 keeps this minimal — only ruler-tier.

    Many saves store marriage history in `family_data.spouse` with dates.
    We yield once per ordered (a, b) pair to avoid duplicates.
    """
    seen: set[tuple[str, str, int]] = set()
    for cid, cdata in chars.items():
        family = cdata.get("family_data") if isinstance(cdata, dict) else None
        if not isinstance(family, dict):
            continue
        spouses = _aslist(family.get("spouse") or family.get("spouses"))
        for sp in spouses:
            spouse_id = _strify(sp.get("character") if isinstance(sp, dict) else sp)
            if not spouse_id:
                continue
            date = _parse_date(sp.get("date") if isinstance(sp, dict) else None)
            if not date:
                continue
            year = date[0]
            key = tuple(sorted([str(cid), spouse_id])) + (year,)
            if key in seen:
                continue
            seen.add(key)
            a = _make_actor(str(cid), chars)
            b = _make_actor(spouse_id, chars)
            eid = make_event_id(
                Source.SAVE_IMPORT,
                EventType.MARRIAGE,
                year,
                salt_parts=[*sorted([str(cid), spouse_id])],
            )
            yield ChronicleEvent(
                event_id=eid,
                source=Source.SAVE_IMPORT,
                type=EventType.MARRIAGE,
                year=year,
                month=date[1],
                day=date[2],
                primary_actors=[a, b],
                outcome=Outcome.SUCCESS,
            )


# ---------- helpers ----------


def _get(d: Any, *path: str) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _aslist(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return [v]


def _strify(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (str, int)):
        return str(v)
    if isinstance(v, dict):
        # rakaly sometimes wraps tokens as {"key": "..."} or {"name": "..."}
        for k in ("key", "name", "value"):
            if k in v:
                return str(v[k])
    return str(v)


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(v: Any) -> tuple[int, int, int] | None:
    """Parse PDX dates. Common shapes: 'YYYY.M.D' string or [Y, M, D] list."""
    if v is None:
        return None
    if isinstance(v, list) and len(v) >= 3:
        try:
            return int(v[0]), int(v[1]), int(v[2])
        except (TypeError, ValueError):
            return None
    if isinstance(v, str):
        parts = v.split(".")
        if len(parts) >= 3:
            try:
                return int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                return None
    if isinstance(v, int):
        # rakaly sometimes emits dates as packed ints — out of scope.
        return None
    return None
