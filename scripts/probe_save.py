"""Quick structural probe: print enough of the save JSON to pick filters."""
from __future__ import annotations

import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
parsed = json.loads(p.read_text(encoding="utf-8"))

print("date:", parsed.get("date") or parsed.get("meta_data", {}).get("meta_date"))

# Sample one dead character
dead = parsed.get("dead_unprunable") or {}
keys = list(dead.keys())
print("dead count:", len(keys))
for cid in keys[:3]:
    c = dead[cid]
    print(f"--- dead {cid} keys ---", list(c.keys())[:30])
    if isinstance(c.get("dead_data"), dict):
        print("  dead_data keys:", list(c["dead_data"].keys())[:20])
        print("  dead_data sample:", {k: c["dead_data"][k] for k in list(c["dead_data"].keys())[:8]})

# Look for war / title-history-ish keys
for k in sorted(parsed.keys()):
    v = parsed[k]
    desc = type(v).__name__
    if isinstance(v, (dict, list)):
        desc += f"[{len(v)}]"
    if any(s in k.lower() for s in ("war", "title", "combat", "battle", "history")):
        print(f"top-key {k!r}: {desc}")

# landed_titles structure
lt = parsed.get("landed_titles")
if isinstance(lt, dict):
    sub = list(lt.keys())[:5]
    print("landed_titles keys:", sub)
    for s in sub[:2]:
        v = lt[s]
        if isinstance(v, dict):
            print(f"  {s} keys:", list(v.keys())[:30])
