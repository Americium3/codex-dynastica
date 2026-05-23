"""Second probe: activity_manager.completed structure + relations.active_relations
+ verify combat_results dates parse + sample artifact history shapes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

parsed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
PLAYER_ID = 33634852

# activity_manager.completed
am = parsed.get("activity_manager") or {}
comp = am.get("completed")
print("completed type:", type(comp).__name__,
      "len:", len(comp) if hasattr(comp, "__len__") else "?")
if isinstance(comp, dict):
    print("completed keys (first 10):", list(comp.keys())[:10])
    for k in list(comp.keys())[:2]:
        v = comp[k]
        if isinstance(v, dict):
            print(f"  completed.{k} keys:", list(v.keys())[:25])
            print("  sample:", {kk: v[kk] for kk in list(v.keys())[:12]})
elif isinstance(comp, list):
    print("completed sample first:", comp[0] if comp else None)

# Player's owned schemes
print("\n--- player's own scheme(s) ---")
schemes_active = (parsed.get("schemes") or {}).get("active") or {}
pl = (parsed.get("living") or {}).get(str(PLAYER_ID)) or {}
ad = pl.get("alive_data") or {}
ts = ad.get("targeting_schemes") or []
own = ad.get("schemes") or []
print("alive_data.schemes (player owns):", own)
print("alive_data.targeting_schemes (aimed at player):", ts)
for sid in own + ts:
    s = schemes_active.get(str(sid))
    if isinstance(s, dict):
        print(f"  scheme {sid}:", {k: s.get(k) for k in ('type', 'status', 'owner', 'target', 'progress', 'date', 'secrecy')})

# Relations
print("\n--- relations.active_relations sample ---")
relations = (parsed.get("relations") or {}).get("active_relations") or {}
print("type:", type(relations).__name__,
      "len:", len(relations) if hasattr(relations, "__len__") else "?")
if isinstance(relations, dict):
    keys = list(relations.keys())[:5]
    print("rel keys (first 5):", keys)
    for k in keys[:2]:
        v = relations[k]
        if isinstance(v, dict):
            print(f"  relations[{k}] keys:", list(v.keys())[:20])
            print("  sample:", {kk: v[kk] for kk in list(v.keys())[:10]})

# Look for spouse/marriage with date specifically
print("\n--- searching relations for spouse/lover/friend ---")
if isinstance(relations, dict):
    for k, v in list(relations.items())[:200]:
        if isinstance(v, dict) and any(s in str(v).lower() for s in ("spouse", "marriage")):
            print(f"  found {k}:", str(v)[:300])
            break

# Artifact: find one owned by player
print("\n--- artifact owned by player ---")
artifacts = (parsed.get("artifacts") or {}).get("artifacts") or {}
for aid, a in list(artifacts.items())[:5000]:
    if isinstance(a, dict) and a.get("owner") == PLAYER_ID:
        print(f"  artifact {aid}: name={a.get('name')!r} type={a.get('type')} rarity={a.get('rarity')}")
        hist = a.get("history") or {}
        if isinstance(hist, dict):
            ents = hist.get("entries") or []
            print(f"    history entries ({len(ents)}):")
            for e in ents[:5]:
                print("     ", e)
        break

# Combat_results: ensure the dates work
print("\n--- combat_results dates (sample 5) ---")
combats = (parsed.get("combats") or {}).get("combat_results") or {}
for k, v in list(combats.items())[:5]:
    if isinstance(v, dict):
        print(f"  combat {k}: start={v.get('start_date')} end={v.get('end_date')} win={v.get('win')} winning_side={v.get('winning_side')} leader={v.get('leader')}")
