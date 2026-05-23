# Roadmap

**English** · [简体中文](ROADMAP.zh-CN.md)

Vox Dynastica focuses on **dynastic / primary-title history**. Family-history (every cousin's birth, every great-aunt's death) is being split into a separate sibling project so this one can stay sharp.

Phases are shippable and useful on their own.

## Phase 0 — Court Historian + Peasant Ballad MVP ✅

End-to-end pipeline. **Supports save-file import**, not just live event hooks. No game UI yet — output is browser HTML.

- [x] Event JSON Schema, common to save-import and live-hook
- [x] Pydantic models
- [x] SQLite storage with idempotent upserts
- [x] Save-file importer (rakaly subprocess wrapper + tolerant extractor)
- [x] Live-hook JSONL watcher (one-shot + tailing)
- [x] Claude API client with prompt caching + cost tracking
- [x] Dry-run mock client
- [x] Two narrative agent prompts (Court Historian, Peasant Ballad)
- [x] Generator orchestrator
- [x] Static HTML renderer (parchment, dual column)
- [x] CLI (`import`, `import-json`, `ingest`, `watch`, `generate`, `render`, `stats`)
- [x] Fixture data + end-to-end smoke test
- [x] Bilingual EN + zh-CN across CLI / HTML chrome / LLM output

## Phase 0.1 — Dynastic title-holder scope + local-model backend ✅

Real saves break the broad extractor (a 1034 save has 93k dead characters). Phase 0.1 narrows the eye to **the player's primary title** and adds an offline LLM path.

- [x] **Ollama local-model client** (`OllamaClient` in `agents/base.py`) — implements the `LLMClient` protocol; strips Anthropic-specific `cache_control`; talks to `http://localhost:11434/api/chat` via stdlib `urllib`; defaults to `gemma3:27b`. Local runs report \$0 cost.
- [x] **CLI:** `--backend {claude,ollama,dry-run}`, `--ollama-model`, `--ollama-url`, `--agent` filter.
- [x] **Project-local rakaly:** `parsers/save_import.py` finds `<repo>/bin/rakaly[.exe]` then `$CHRONICLER_RAKALY` then `$PATH` — no system pollution.
- [x] **`scripts/import_dynasty.py`** — title-holder-scoped real-save importer:
  - Walks `landed_titles.landed_titles[primary_id].history` to enumerate every past holder of the player's primary title.
  - For each holder pulls: their **death**, their **first heir's birth**, their **first heir's death**, and their **marriage**.
  - For **active wars** where the primary title's current holder is a participant: emits an "ongoing war" event with casus belli + opposing leader.
  - For the **current holder**, surfaces **significant traits** (illness, disability, aging) as state-of-the-realm entries dated to the save.
- [x] **Title-id → holder-char-id resolver** — `wars.active_wars` participants are character ids, but the cross-check that links the war to the *primary title* itself goes through this map.
- [x] **Player-context injection in briefs** — every prompt now carries reigning ruler name + primary title + dynasty house, so the LLM stops inventing "King Alaric" out of thin air.
- [x] **`--max-per-type` subquota cap** — no single event class can drown the chronicle.
- [x] **CK3 CJK name decoder** — `Zihua_5B50_534E` → `Zihua 子华`, `Wenju_6587_4E3E` → `Wenju 文举`.
- [x] **English Court Historian prompt rewrite** — drop untranslated Latin; archaic but readable English (Bede *in modern translation*).
- [ ] Cost-curve benchmarking on 3–5 diverse real saves
- [ ] Recover wars / coronations / marriages from saves with the newer `landed_titles[*].history` shape (Phase 0 default extractor still misses these)

## Phase 0.2 — Player-selectable scope: narrow / middle / wide

Add a single CLI flag (and, in Phase 1, an in-game setting) so the player can choose how wide the chronicle's eye should be:

- [ ] **narrow** — player's own dynastic house only. Births, deaths, marriages of house members. Suitable for landed rulers who want a family chronicle and for landless adventurers whose bloodline is still the unit.
- [ ] **middle** — narrow PLUS the lieges of any realms the player has resided in. Designed for landless adventurer playthroughs where the realm is borrowed, not owned.
- [ ] **wide** — every prominent ruler in the known world (the original Phase 0 default).
- [ ] Per-type subquotas and recency windows configurable per scope.
- [ ] Auto-pick a sensible scope from the player's lifestyle (landed → dynastic, wandering → middle, ironman → narrow).

## Phase 1 — In-game Royal Library UI + cloud-API picker

Hard requirement: **visually indistinguishable from vanilla CK3**. It should feel like an official DLC, not a modder add-on. Adds RimTalk-style provider/key/model selection in mod settings so players can use any cloud LLM (or keep using their local Ollama).

Vanilla-fidelity principles (non-negotiable):
- Do not draw new frames/buttons/dividers — reference `gfx/interface/...` textures only
- Base layout on closest vanilla precedents: `window_encyclopedia.gui`, `window_struggle.gui`, `window_decisions.gui`
- Reuse vanilla templates: `window_background`, `scrollbox`, `scrollbar_vertical`, `button_standard`, `background_paper`, `tooltip_widget`
- Vanilla SFX only (`event:/SFX/UI/...`), vanilla fonts only (`cg_16b` / `cg_24b`), vanilla color tags (`#H`, `#italic`, `#weak`)
- Entry point inside an existing vanilla button strip — no floating new buttons
- ESC / right-click / drag / pin behavior matches vanilla exactly

Tasks:
- [ ] Vanilla UI audit — pick a precedent window, enumerate reusable templates
- [ ] `.gui` files for Royal Library window: bookshelf view, single-book reader, side-by-side comparison
- [ ] Entry button on character window action strip
- [ ] Localization injection pipeline: Python writes generated content to mod's `localization/replace/` YAML
- [ ] Naming convention for localization keys: `chronicle_<year>_<agent>_<event_id>`
- [ ] Hot reload (save/load or console command)
- [ ] Post-war event: "Your historian has completed a new chronicle volume" — approve / revise / execute (hook only; effects in Phase 3)
- [ ] LLM-generated book titles and chapter ornaments
- [ ] Quality gate: blind screenshot test — third party cannot tell which screenshots are modded
- [ ] Correct scaling at 50% / 100% / 150% UI scale
- [ ] **Cloud-API picker in mod settings** — RimTalk-style: dropdown of providers (Anthropic, OpenAI, OpenRouter, Ollama-local), text fields for key + model, sane defaults, latency / cost preview before commit

## Phase 2 — Enemy + Church perspectives

From single voice to multi-voice contrast — the biggest immersion jump.

- [ ] Enemy historian prompt (reverse polarity, opponent-nation subject)
- [ ] Church chronicle prompt (theological framing, scripture-style quotes)
- [ ] Agent persona registry: each agent backed by a real CK3 character with traits
- [ ] Event schema extension: `factions_involved`, `religions_involved`, `witnesses` control who can "know" what
- [ ] Cross-border circulation: travelers/envoys as information carriers; event "A Byzantine traveler brings a volume that records..."
- [ ] Church version injected via bishop/pope characters
- [ ] Library UI: "by event" lookup mode; horizontal listing across perspectives; highlight divergence points (casualty counts, blame, motive)

## Phase 3 — Historical drift, physical carriers, gameplay reverse hooks

From flavor layer to systems layer — history begins to influence play.

- [ ] **Drift**: every 50 years, "transcription" pass — LLM rewrites old version with deliberate mythologization, character-merging, political recoloring, memory errors. Preserve all versions for comparison.
- [ ] **Physical carriers**: each chronicle bound to a library building in a holding; siege / sack / heretic raid / fire destroys that copy; "duplicate" mechanic for important works; orphan-copy flag when only foreign libraries hold a work.
- [ ] **Archaeology**: decisions "Renovate royal library" (chance to recover lost versions) and "Send scholars to Byzantium" (chance to obtain foreign perspectives); first-time foreign-perspective viewing triggers a special emotional-impact event.
- [ ] **Gameplay reverse hooks**:
  - Descendant reading ancestor heroics → stress relief / "inspired" modifier
  - Enemy version reaching court → legitimacy decrease event
  - High-spread peasant ballad → popular opinion debuff, revolt chance up
  - Church canonization version → permanent dynasty holy modifier
  - Executing a historian → next historian more sycophantic (more exaggeration but more legitimacy bonus)
  - Heretical secret history discovered → religious tribunal event
- [ ] **Unreliable historian systematized**: historian traits drive explicit prompt-bias sliders (sycophancy / piety / erudition); court position UI shows preview of how future writing will be shaped.
