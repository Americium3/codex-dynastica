"""Find the player and dynasty so we can filter notable deaths."""
from __future__ import annotations

import json
import sys
from pathlib import Path

parsed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("save date:", parsed.get("date"))
print("played_character:", parsed.get("played_character"))
print("currently_played_characters:", parsed.get("currently_played_characters"))

pc = parsed.get("played_character")
if isinstance(pc, dict):
    print("played_character keys:", list(pc.keys()))

# Sample one living character
living = parsed.get("living") or {}
sample_ids = list(living.keys())[:1]
for cid in sample_ids:
    c = living[cid]
    print(f"--- living {cid} keys ---", list(c.keys())[:40])
    for k in ("first_name", "dynasty_house", "dynasty", "culture", "faith", "landed_data"):
        print(f"  {k}:", c.get(k))

# Find dead with nicknames or held titles
dead = parsed.get("dead_unprunable") or {}
hits = 0
for cid, c in dead.items():
    if hits >= 5:
        break
    dd = c.get("dead_data") or {}
    if dd.get("titles") or dd.get("liege") or dd.get("government"):
        print(f"notable dead {cid}:", {k: c.get(k) for k in ("first_name", "dynasty_house", "culture", "faith")}, "dead_data:", dd)
        hits += 1
print(f"\nfound {hits} dead chars with dead_data extras")

# Distribution of death dates
years = {}
for c in list(dead.values())[:5000]:  # sample
    dd = c.get("dead_data") or {}
    d = dd.get("date")
    if isinstance(d, str) and "." in d:
        y = int(d.split(".")[0])
        years[y] = years.get(y, 0) + 1
print("death year distribution (first 5000 sample):")
for y in sorted(years)[-15:]:
    print(f"  {y}: {years[y]}")
