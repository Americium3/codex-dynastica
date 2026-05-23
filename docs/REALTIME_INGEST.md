# Real-time Event Ingest

**Phase 0.4** · [简体中文](REALTIME_INGEST.zh-CN.md)

## Why

Phase 0–0.3 worked off save files: the player saves the game, Python parses the `.ck3` with rakaly, the importer extracts events, the agents narrate them. That's fine for a finished campaign and indispensable for retrospectives — but in active play it forces a save-then-import dance and dumps a whole batch on the LLM at once.

Phase 0.4 adds the alternative: while CK3 is running, the mod writes one JSON line per noteworthy event to a log file; Python tails that file and either stores or immediately narrates each event as it arrives. No batch, no manual save, no `--max-events` cap — each event is a small, independent LLM call.

## Architecture

```
┌────────────────────┐       ┌───────────────────┐       ┌─────────────────────┐
│   CK3 (running)    │       │  script.log /     │       │  Python tailer      │
│                    │       │  events.jsonl     │       │  (chronicler watch) │
│  on_ruler_death,   │  →    │                   │  →    │                     │
│  on_battle_won,    │  via  │  {…JSON line…}    │ tail  │  validate → DB →    │
│  on_marriage, …    │ debug │  {…JSON line…}    │ poll  │  (optionally) LLM   │
│                    │  _log │  …                │       │                     │
└────────────────────┘       └───────────────────┘       └─────────────────────┘
```

Three pieces, decoupled at the JSONL boundary:

1. **CK3 mod side** — `on_action` hooks call a `scripted_effect` that builds a one-line JSON string and writes it via `debug_log`. CK3's `debug_log` effect appends to `Documents/Paradox Interactive/Crusader Kings III/logs/script.log` (or `script_event_errors.log` depending on the build). We pin a known filename via the mod's effect convention.
2. **The JSONL file** — the contract surface. Same schema as Phase 0's save-import path (`schemas/event.schema.json`), with `source = "live_hook"`. This is what makes the system testable end-to-end: you can hand-write a JSONL and prove the pipeline works without launching CK3.
3. **Python tailer** — `chronicler watch <jsonl> --db chronicle.db` polls the file, validates each line against `ChronicleEvent`, upserts to SQLite, and (if `--generate` is set) immediately runs the agents.

## Why `debug_log` (and not autosave polling)

CK3 has no first-class event-export API. The three options we evaluated:

| approach | verdict |
|---|---|
| Autosave polling — `chronicler import` on every autosave | ❌ what the user explicitly rejected: latency, lots of duplicate work, batches |
| Memory reading — read CK3's process memory | ❌ fragile across patches, anti-cheat-adjacent, won't survive Steam updates |
| **`debug_log` from scripted effects** | ✅ official, stable across patches, mod-only, leaves a tailable file |

`debug_log` exists for modder diagnostics, but the string it appends can be anything — including a one-line JSON envelope. Many Total-Conversion mods already use it for telemetry. Performance impact is negligible (one line per real event, not per tick).

## The CK3-side contract

The mod registers handlers in `events/` or `common/on_action/` for the actions we care about. Each handler builds a JSON-ish string and passes it to `debug_log`. Example (illustrative — actual `.txt` files live under `mod/` and ship with Phase 1):

```paradox
# common/on_action/vox_dynastica_on_actions.txt
on_ruler_death = {
    effect = {
        vox_dynastica_log_event = {
            EVENT_TYPE = ruler_death
            ACTOR = root
            CAUSE = "[root.GetDeathReasonKey]"
        }
    }
}
```

```paradox
# common/scripted_effects/vox_dynastica_log_event.txt
vox_dynastica_log_event = {
    # Build the JSON line. CK3 string-interp does most of the work.
    debug_log = "VD_EVENT|{\"event_id\":\"live_hook:$EVENT_TYPE$:[GetGameYear]:[$ACTOR$.GetID]\",\"source\":\"live_hook\",\"type\":\"$EVENT_TYPE$\",\"year\":[GetGameYear],\"month\":[GetGameMonth],\"day\":[GetGameDay],\"primary_actors\":[{\"character_id\":\"[$ACTOR$.GetID]\",\"name\":\"[$ACTOR$.GetFirstNameNoTooltip]\",\"dynasty\":\"[$ACTOR$.GetDynasty.GetName]\",\"culture\":\"[$ACTOR$.GetCulture.GetName]\",\"religion\":\"[$ACTOR$.GetReligion.GetName]\"}],\"tags\":[\"$CAUSE$\"]}"
    }
```

The `VD_EVENT|` prefix is a sentinel so the tailer can grep our lines out of `script.log` (which also collects unrelated modder spam). The tailer strips that prefix before `json.loads`.

A two-step rotation runs alongside:

* The mod calls `debug_log` for every noteworthy event.
* A small companion Python script (`scripts/extract_vd_events.py`, included with the mod) periodically scans `script.log` for `VD_EVENT|` lines and writes the JSON tails to `events.jsonl` (creating it if absent). The Python tailer watches `events.jsonl`, not `script.log` directly, so CK3's diagnostic noise stays separated.

## The on_action set we plan to hook

Phase 0.4 documents these; Phase 1 ships the actual `.txt` files.

| on_action | EventType | min_significance default |
|---|---|---|
| `on_ruler_death` | `ruler_death` / `murder` | 95 — always narrated |
| `on_birth` (if heir) | `birth` | 64 — narrated (heir tag bumps to 76) |
| `on_marriage` | `marriage` | 60 — narrated |
| `on_war_won` / `on_war_lost` | `war_end` | 92 — always narrated |
| `on_battle_won` / `on_battle_lost` | `battle` | 82 — narrated |
| `on_title_gain_inheritance` | `coronation` | 88 — always narrated |
| `on_great_holy_war_*` | `great_holy_war` | 92 — always narrated |
| `on_faith_created` | `religion_change` / `heresy_outbreak` | 74–78 — narrated |
| `on_county_culture_change` | (logged, not narrated by default) | 30 — DB only |
| `on_artifact_claimed` (rare only) | `artifact_acquired` | 55 + rarity bump |

`min_significance` below the watcher's threshold means the event still lands in the DB (so future retrospectives include it) but skips the LLM call, saving tokens.

## End-to-end smoke test (no CK3 needed)

```bash
# Terminal 1: tail the file
chronicler watch ./events.jsonl --db chronicle.db --generate \
    --backend ollama --lang en,zh

# Terminal 2: pretend to be the game
cat >> ./events.jsonl <<'EOF'
{"event_id":"live_hook:ruler_death:1066:abc123","source":"live_hook","type":"ruler_death","year":1066,"primary_actors":[{"character_id":"42","name":"Harold","dynasty":"Godwin"}],"tags":["death_battle"]}
EOF
```

The watcher should print the accepted event, then `[court_historian/en]`, `[court_historian/zh]`, `[peasant_ballad/en]`, `[peasant_ballad/zh]` lines as each narrative lands.

## What lives in which phase

* **Phase 0.4** (this one):
  * Python `watch --generate` pipeline ✅
  * `--min-significance` LLM-cost gate ✅
  * This spec doc ✅
  * Per-scope strictness presets (`narrow=6 / medium=12 / wide=24`) ✅
* **Phase 1** (planned):
  * The actual CK3 mod `.txt` files (`on_action`, `scripted_effects`)
  * `scripts/extract_vd_events.py` — script.log → events.jsonl bridge
  * In-game settings UI for the LLM provider + min-significance slider
* **Phase 2+**:
  * Live ingest of multi-voice (enemy / church) — same JSONL pipeline, just more agents
