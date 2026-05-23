"""Probe the 1006 Ming save: player + primary title + war/trait shape."""
from __future__ import annotations

import json
import sys
from pathlib import Path

parsed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

print("date:", parsed.get("date"))
pc = parsed.get("played_character") or {}
pid = pc.get("character")
print("player id:", pid, "  name field:", pc.get("name"))

living = parsed.get("living") or {}
dead = parsed.get("dead_unprunable") or {}
chars = {**dead, **living}
player = chars.get(str(pid)) or {}
print("player first_name:", player.get("first_name"))
print("player dynasty_house:", player.get("dynasty_house"))

ld = player.get("landed_data") or {}
print("\nlanded_data keys:", list(ld.keys())[:30])
print("landed_data.domain:", ld.get("domain"))
print("landed_data.primary_title:", ld.get("primary_title") or ld.get("primary"))

# landed_titles structure
lt_root = parsed.get("landed_titles") or {}
print("\nlanded_titles top keys:", list(lt_root.keys())[:10])
lt = lt_root.get("landed_titles") or {}
print(f"landed_titles.landed_titles: dict[{len(lt)}]")
# Sample one
if lt:
    sample_id = list(lt.keys())[0]
    s = lt[sample_id]
    print(f"sample title {sample_id} keys:", list(s.keys())[:30])
    print("  holder:", s.get("holder"), "  key:", s.get("key"))

# Look at the player's primary title (first domain entry)
domain = ld.get("domain") or []
if domain:
    primary_id = str(domain[0])
    pt = lt.get(primary_id)
    if pt:
        print(f"\nplayer primary title {primary_id}:")
        for k in ("key", "name", "holder", "history", "de_jure_liege", "tier", "claim", "succession"):
            v = pt.get(k)
            if v is not None:
                print(f"  {k}:", v if not isinstance(v, (dict, list)) else f"{type(v).__name__}[{len(v)}]")
        # title history?
        hist = pt.get("history") or pt.get("title_history")
        if hist:
            print("  history sample:", str(hist)[:300])

# Wars
wars_root = parsed.get("wars") or {}
print("\nwars top keys:", list(wars_root.keys()) if isinstance(wars_root, dict) else "?")
active = wars_root.get("active_wars") if isinstance(wars_root, dict) else None
if isinstance(active, dict):
    print(f"active_wars: dict[{len(active)}]")
    # sample
    for wid, war in list(active.items())[:1]:
        if isinstance(war, dict):
            print(f"sample war {wid} keys:", list(war.keys())[:40])
            for k in ("name", "name_token", "war_name", "attackers", "defenders", "attacker", "defender",
                     "start_date", "claimant", "casus_belli", "title_name"):
                v = war.get(k)
                if v is not None:
                    print(f"  {k}:", v if not isinstance(v, (dict, list)) else f"{type(v).__name__}[{len(v) if hasattr(v, '__len__') else '?'}] " + str(v)[:200])

# Traits lookup
tl = parsed.get("traits_lookup") or {}
print(f"\ntraits_lookup: type={type(tl).__name__} len={len(tl)}" if isinstance(tl, (dict, list)) else "?")
if isinstance(tl, list):
    print("first 10 traits:", tl[:10])
    print("last 10 traits:", tl[-10:])
elif isinstance(tl, dict):
    print("sample trait entries:", list(tl.items())[:5])

# Player's traits
pt_traits = player.get("traits") or []
print("\nplayer traits (raw ids):", pt_traits[:30])
if isinstance(tl, list):
    print("player traits (decoded):", [tl[i] if 0 <= i < len(tl) else f"<{i}>" for i in pt_traits[:30]])
elif isinstance(tl, dict):
    print("player traits (decoded):", [tl.get(str(i)) for i in pt_traits[:30]])

# Family data
fd = player.get("family_data") or {}
print("\nplayer family_data keys:", list(fd.keys())[:20])
for k in ("primary_spouse", "spouse", "child", "former_spouses"):
    v = fd.get(k)
    if v is not None:
        print(f"  {k}:", v if not isinstance(v, list) else f"list[{len(v)}] e.g. {v[:5]}")
