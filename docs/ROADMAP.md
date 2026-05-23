# Roadmap

**English** · [简体中文](ROADMAP.zh-CN.md)

The project is split into four phases. Each phase is shippable and useful on its own.

## Phase 0 — Court Historian + Peasant Ballads (current MVP)

End-to-end pipeline. **Must support save-file import**, not just live event hooks. No game UI yet — output is browser HTML.

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
- [ ] Cost-curve benchmarking on 3–5 diverse saves (short / long / different cultures + religions)
- [ ] Subjective output quality review (no out-of-character slips, no modern terms)

## Phase 1 — In-game Royal Library UI

Hard requirement: **visually indistinguishable from vanilla CK3**. It should feel like an official DLC, not a modder add-on.

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
