"""Probe player + dynasty + war structure for the narrow-scope chronicle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

parsed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

PLAYER_ID = 16869602
living = parsed.get("living") or {}
dead = parsed.get("dead_unprunable") or {}

# Player record
pl = living.get(str(PLAYER_ID)) or dead.get(str(PLAYER_ID))
print("player keys:", list(pl.keys()) if pl else None)
print("player first_name:", pl.get("first_name") if pl else None)
print("player dynasty_house:", pl.get("dynasty_house") if pl else None)
fd = (pl or {}).get("family_data") or {}
print("family_data keys:", list(fd.keys())[:30])
for k in ("father", "mother", "spouse", "child", "sibling", "primary_spouse"):
    v = fd.get(k)
    if v is not None:
        print(f"  {k}:", v if not isinstance(v, list) else f"list[{len(v)}] e.g. {v[:5]}")

# Dynasties + houses
dynasties = parsed.get("dynasties") or {}
print("\ndynasties top-level keys:", list(dynasties.keys())[:10])
if isinstance(dynasties, dict):
    for k in list(dynasties.keys())[:3]:
        v = dynasties[k]
        if isinstance(v, dict):
            print(f"  dynasties.{k} keys:", list(v.keys())[:20])
            # sample
            sub = list(v.keys())[:2]
            for s in sub:
                vv = v[s]
                if isinstance(vv, dict):
                    print(f"    dynasties.{k}.{s} keys:", list(vv.keys())[:20])
                    print(f"    dynasties.{k}.{s} sample:", {kk: vv.get(kk) for kk in list(vv.keys())[:6]})

# Houses
houses = (parsed.get("dynasties", {}) or {}).get("dynasty_house") or {}
if not isinstance(houses, dict):
    houses = parsed.get("dynasty_houses") or {}
print("\nhouses count:", len(houses) if isinstance(houses, dict) else "?")
if isinstance(houses, dict):
    target = (pl or {}).get("dynasty_house")
    if target is not None and str(target) in houses:
        h = houses[str(target)]
        print(f"player's house {target}:", {k: h.get(k) for k in list(h.keys())[:20]})

# Wars
print("\n--- wars (active) ---")
wars = parsed.get("wars") or {}
for wid, w in list(wars.items())[:3]:
    if isinstance(w, dict):
        print(f"war {wid} keys:", list(w.keys())[:30])
        print("  name:", w.get("name"))
        for k in ("attackers", "defenders", "attacker", "defender", "attacker_participants", "defender_participants"):
            v = w.get(k)
            if v is not None:
                print(f"  {k}:", v if not isinstance(v, list) else f"list[{len(v)}] {v[:5]}")

# Check for past wars under different keys
for key in ("past_wars", "history_wars", "war_log", "fought_wars"):
    if key in parsed:
        print(f"FOUND {key}: type={type(parsed[key]).__name__}, len={len(parsed[key]) if isinstance(parsed[key], (dict, list)) else '?'}")

# Search character record for war traces
print("\nplayer alive_data keys:", list((pl or {}).get("alive_data", {}).keys())[:20])
ad = (pl or {}).get("alive_data") or {}
for k in ("wars", "past_wars", "battles", "victories", "defeats", "war_history"):
    if k in ad:
        v = ad[k]
        print(f"  alive_data.{k}:", v if not isinstance(v, (list, dict)) else f"{type(v).__name__}[{len(v)}]")

# Combats
combats = parsed.get("combats") or {}
print(f"\ncombats: dict[{len(combats)}]")
for cid, comb in list(combats.items())[:1]:
    if isinstance(comb, dict):
        print(f"  combat {cid} keys:", list(comb.keys())[:30])
