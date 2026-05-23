"""Probe the 🟡 untapped sections: relations, combats, schemes, stories,
artifacts, activities, laws — on the 1006 Ming save.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

parsed = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

PLAYER_ID = 33634852
living = parsed.get("living") or {}
dead = parsed.get("dead_unprunable") or {}
chars = {**dead, **living}


def banner(label):
    print("\n" + "=" * 8 + " " + label + " " + "=" * 8)


def keys_of(obj, n=20):
    if isinstance(obj, dict):
        return list(obj.keys())[:n]
    return type(obj).__name__


# 1. relations + opinions
banner("relations / opinions")
relations = parsed.get("relations")
print("relations type:", type(relations).__name__,
      "len:", len(relations) if hasattr(relations, "__len__") else "?")
if isinstance(relations, dict):
    print("relations keys:", list(relations.keys())[:20])
    for k in list(relations.keys())[:3]:
        v = relations[k]
        if isinstance(v, dict):
            print(f"  relations.{k} keys:", list(v.keys())[:20])
            if v:
                sub = list(v.keys())[0]
                print(f"    sample relations.{k}.{sub}:", str(v[sub])[:300])

# 2. combats
banner("combats")
combats = parsed.get("combats")
print("combats type:", type(combats).__name__,
      "len:", len(combats) if hasattr(combats, "__len__") else "?")
if isinstance(combats, dict):
    print("combats keys:", list(combats.keys()))
    for k in list(combats.keys())[:2]:
        v = combats[k]
        print(f"  combats.{k} type={type(v).__name__} len={len(v) if hasattr(v, '__len__') else '?'}")
        if isinstance(v, dict) and v:
            sub = list(v.keys())[0]
            sample = v[sub]
            print(f"    combats.{k}.{sub} keys:", list(sample.keys())[:30] if isinstance(sample, dict) else type(sample).__name__)
            if isinstance(sample, dict):
                for kk in ("date", "location", "province", "attacker", "defender", "winner",
                           "casualties", "primary_attacker", "primary_defender",
                           "regiments", "battle"):
                    if kk in sample:
                        val = sample[kk]
                        print(f"      {kk}:", str(val)[:200])

# 3. schemes
banner("schemes")
schemes = parsed.get("schemes")
print("schemes type:", type(schemes).__name__,
      "len:", len(schemes) if hasattr(schemes, "__len__") else "?")
if isinstance(schemes, dict):
    print("schemes top keys:", list(schemes.keys())[:20])
    # Player's schemes
    pl = chars.get(str(PLAYER_ID), {})
    pl_schemes = (pl.get("alive_data") or {}).get("schemes") or []
    print("player schemes (ids):", pl_schemes)
    # Find sample of any scheme
    if isinstance(schemes, dict):
        for k in list(schemes.keys())[:1]:
            v = schemes[k]
            if isinstance(v, dict):
                print(f"  schemes.{k} keys:", list(v.keys())[:30])
                # If it's a dict-of-schemes (id → scheme)
                if v:
                    inner = list(v.keys())[0]
                    samp = v[inner]
                    if isinstance(samp, dict):
                        print(f"    schemes.{k}.{inner} keys:", list(samp.keys())[:25])
                        print("    sample:", {kk: samp[kk] for kk in list(samp.keys())[:10]})

# 4. stories
banner("stories")
stories = parsed.get("stories")
print("stories type:", type(stories).__name__,
      "len:", len(stories) if hasattr(stories, "__len__") else "?")
if isinstance(stories, dict):
    print("stories top keys:", list(stories.keys())[:20])
    for k in list(stories.keys())[:2]:
        v = stories[k]
        print(f"  stories.{k} type={type(v).__name__}")
        if isinstance(v, dict) and v:
            sub = list(v.keys())[0]
            if isinstance(v[sub], dict):
                print(f"    stories.{k}.{sub} keys:", list(v[sub].keys())[:20])
                print("    sample:", {kk: v[sub][kk] for kk in list(v[sub].keys())[:8]})

# 5. artifacts (top-level)
banner("artifacts")
artifacts = parsed.get("artifacts")
print("artifacts type:", type(artifacts).__name__,
      "len:", len(artifacts) if hasattr(artifacts, "__len__") else "?")
if isinstance(artifacts, dict):
    print("artifacts top keys:", list(artifacts.keys())[:20])
    for k in list(artifacts.keys())[:3]:
        v = artifacts[k]
        print(f"  artifacts.{k} type={type(v).__name__} len={len(v) if hasattr(v, '__len__') else '?'}")
        if isinstance(v, dict) and v:
            sub = list(v.keys())[0]
            samp = v[sub]
            if isinstance(samp, dict):
                print(f"    artifacts.{k}.{sub} keys:", list(samp.keys())[:25])
                print("    sample:", {kk: samp[kk] for kk in list(samp.keys())[:8]})

# 6. activities
banner("activities (activity_manager)")
am = parsed.get("activity_manager")
print("activity_manager type:", type(am).__name__,
      "len:", len(am) if hasattr(am, "__len__") else "?")
if isinstance(am, dict):
    print("activity_manager keys:", list(am.keys())[:20])
    for k in ("activities", "past_activities", "activity_log",
              "completed_activities", "history"):
        if k in am:
            v = am[k]
            print(f"  am.{k} type={type(v).__name__} len={len(v) if hasattr(v, '__len__') else '?'}")
            if isinstance(v, dict) and v:
                sub = list(v.keys())[0]
                print(f"    am.{k}.{sub} keys:", list(v[sub].keys())[:25] if isinstance(v[sub], dict) else type(v[sub]).__name__)

# Player's recent activity hosts/joins (already seen in probe_player)
banner("player activity history (from played_character)")
pc = parsed.get("played_character") or {}
print("activities_hosted:", pc.get("activities_hosted"))
print("activities_attended:", pc.get("activities_attended"))
print("last_open_activity_dates:", pc.get("last_open_activity_dates"))
print("last_hosted_activity_dates:", pc.get("last_hosted_activity_dates"))

# 7. landed_data laws + succession
banner("landed_data.laws / succession")
pl = chars.get(str(PLAYER_ID), {})
ld = pl.get("landed_data") or {}
laws = ld.get("laws")
print("laws type:", type(laws).__name__,
      "len:", len(laws) if hasattr(laws, "__len__") else "?")
if isinstance(laws, (dict, list)):
    print("laws sample:", str(laws)[:600])
succession = ld.get("succession")
print("\nsuccession type:", type(succession).__name__,
      "len:", len(succession) if hasattr(succession, "__len__") else "?")
if isinstance(succession, dict):
    print("succession keys:", list(succession.keys())[:20])
    print("succession sample:", {k: succession[k] for k in list(succession.keys())[:8]})

# 8. struggles
banner("struggles")
struggles = parsed.get("struggles")
print("struggles type:", type(struggles).__name__,
      "len:", len(struggles) if hasattr(struggles, "__len__") else "?")
if isinstance(struggles, dict):
    print("struggles keys:", list(struggles.keys())[:10])
    for k in list(struggles.keys())[:1]:
        v = struggles[k]
        print(f"  struggles.{k}:", str(v)[:400])
