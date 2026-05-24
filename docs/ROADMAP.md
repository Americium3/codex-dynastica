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

Real saves break the broad extractor (a late-game save can carry 90k+ dead characters). Phase 0.1 narrows the eye to **the player's primary title** and adds an offline LLM path.

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

## Phase 0.2 — Player-selectable scope + shorter chronicles ✅

A single ``--scope`` CLI flag on ``scripts/import_dynasty.py`` (and, in Phase 1, an in-game setting) lets the player choose how wide the chronicle's eye should be. All scope tiers flow through one CLI surface; the standalone prototype scripts ``import_narrow.py`` / ``import_real_save.py`` remain as historical references only.

- [x] **dynastic** (default) — primary-title spine: holder line, heirs, wars, traits, schemes, stories, artifacts, activities, marriages.
- [x] **narrow** — player's own dynastic house only. Births + deaths of house members in the window. Suitable for landed rulers who want a family chronicle and for landless adventurers whose bloodline is still the unit.
- [x] **middle** — narrow + dynastic. House-member life events overlaid on the primary-title spine. The default sweet spot when in doubt.
- [x] **wide** — middle + every notable landed death in the window across the known world (capped via ``--max-per-type`` because saves carry 90k+ dead NPCs).
- [x] **Shorter chronicles** — Court Historian now targets 1–2 short paragraphs / ~70–130 words (was 2–5 paragraphs / 150–280 words). Peasant Ballad targets 4–10 lines / ~30–70 words (was 8–20 lines / 60–140 words). Default ``max_tokens`` dropped from 800 → 350. Online players can't wait on novella-length entries per event.
- [ ] Auto-pick a sensible scope from the player's lifestyle (landed → dynastic, wandering → middle, ironman → narrow). Deferred — comes with the in-game UI in Phase 1.

## Phase 0.3 — Selective events, era-mood-aware ballads, imagery ×20 ✅

Earlier runs surfaced ~24–27 events per chronicle — too many to read at a sitting. And every peasant ballad still skewed elegiac and reused the same five images. Phase 0.3 fixes both:

- [x] **Significance-based selection** — `scripts/import_dynasty.py` now ranks candidate events by a `SIGNIFICANCE` table (murder/death/war/coronation at the top; trait/activity/story at the bottom), with tag-based nudges (`heir` +12, `title:` +6, `notable_ruler` −15, `house_member` without `heir` −8, rare artifact +10). After per-type trimming, the top N by score is kept; ties broken by recency.
- [x] **Lower defaults** — `--max-per-type` 6 → **3**; new `--max-events` global cap default **12** (was effectively unbounded). Artifact extractor cap 6 → 4. Single-page chronicles by default.
- [x] **`era_mood` per event** — Importer computes a ±15-year dark-event density (deaths, murders, wars, battles, disasters, heresy, holy wars) for each kept event and compares to the chronicle's own mean. Stamps `era_mood = turbulent | ordinary | peaceful`. New optional field on `ChronicleEvent` + JSON Schema; surfaced in `event_brief()` so every agent sees it.
- [x] **Peasant ballad reads `era_mood`** — Prompts (EN + ZH) now combine *event base tone* with *era weather*: a birth in a `turbulent` era still rejoices but admits the missing brother; a death in a `peaceful` era is mourned with unusual weight ("we had not lost a son in twenty harvests"); `ordinary` follows the event's own tone. Removes the systematic elegiac bias.
- [x] **Imagery library ×20** — Both bilingual prompts now carry massively expanded eight-category palettes (weather/food/animals/plants/tools/household/people/seasons): the English bank grew from ~90 → ~1200 items, the Chinese bank from ~90 → ~900 items. Words sub-grouped within each category so the singer can pick "early spring" vs "deep winter" cleanly. Anti-refrain rule kept and tightened.
- [ ] Court Historian likewise should weight tone by `era_mood` (currently only the ballad reads it). Deferred to a small follow-up — the court voice is supposed to stay measured regardless of era, so the bias is more subtle there and needs its own pass.

## Phase 0.4 — Real-time event ingest + tiered selectivity ✅

Save-file imports are great for retrospectives but force a save-then-import dance during active play, and drop a whole batch on the LLM at once. Phase 0.4 reframes the pipeline around the live-hook path that's been sketched since Phase 0 and recalibrates `--scope` so each preset bundles its own strictness.

- [x] **Per-scope strictness presets** — `--scope` now carries both *what to pull* and *how strict the cutoff is*. Phase 0.3 settings become the **medium** tier (matches `dynastic` / `middle`); `narrow` tightens (max_per_type=2, max_events=6, min_live_significance=70); `wide` loosens (max_per_type=5, max_events=24, min_live_significance=40). `--max-per-type` / `--max-events` still override.
- [x] **Significance scoring lifted into `chronicler.scoring`** — the Phase 0.3 `SIGNIFICANCE` table + tag-aware `significance()` are now in a reusable module so both the save importer and the live-hook watcher rank events the same way.
- [x] **`chronicler watch --generate`** — events are narrated as they arrive, one LLM call per event instead of a batch at end-of-session. Backends: `claude` / `ollama` / `dry-run`. Languages and agents are configurable just like in `generate`.
- [x] **`--min-significance` LLM-cost gate** — events scoring below the threshold still hit the database (so future retrospectives include them) but skip the LLM call. Default 55 (matches medium-scope live threshold).
- [x] **Architecture spec** (`docs/REALTIME_INGEST.md`, EN + zh-CN) — documents the CK3-side contract (`debug_log` from `scripted_effect`), the `VD_EVENT|` sentinel, the `script.log` → `events.jsonl` bridge, the planned `on_action` set, and which pieces ship in which phase.
- [ ] **CK3 mod `.txt` files** — actual `on_action` and `scripted_effect` definitions. Deferred to Phase 1, where they ride alongside the in-game UI work. The watcher pipeline is fully testable today by hand-writing JSONL lines.
- [ ] **`scripts/extract_vd_events.py`** — companion `script.log` → `events.jsonl` extractor. Deferred to Phase 1.

## Phase 0.5 — CI bootstrap + test backfill ✅

Phase 0.3 and 0.4 shipped several hundred lines (`scoring.py`, `ScopePreset`, era_mood computation, `watch --generate`) without adding a single test. Phase 0.5 closes the gap before the Phase 1 mod-file work, so future PRs catch regressions automatically.

- [x] **GitHub Actions CI** (`.github/workflows/ci.yml`) — two jobs:
  - `lint` runs `ruff check src tests scripts`
  - `test` runs `pytest -q` on Python 3.11 + 3.12 (3.11 is the floor, 3.12 catches forward-compat drift cheaply)
  - Triggered on every push to every branch + every PR targeting `main`
  - In-flight runs cancelled when a new commit lands on the same ref (saves minutes on rebase storms)
- [x] **Branch protection follow-up** (manual, ruleset on GitHub) — `Require status checks: lint, test (3.11), test (3.12)` should be enabled so `main` can't merge red PRs.
- [x] **Baseline ruff pass** — fixed 96 auto-fixable issues and 6 hand-fixes (loop var renames, `zip(strict=True)`, dead variable, unused import). Added `UP042` (StrEnum migration) and per-file `E402` (sys.path manipulation) to the ignore set with comments explaining why.
- [x] **`tests/test_scoring.py`** (26 tests) — pins SIGNIFICANCE table calibration, tag-aware `significance()` adjustments (heir +12, title +6, notable_ruler −15, house_member −8, rarity +10), SCOPE_PRESETS structure, `resolve_scope()` fallback behavior.
- [x] **`tests/test_era_mood.py`** (15 tests) — covers `stamp_era_mood()` under all three regimes (turbulent / peaceful / ordinary), edge cases (fewer-than-three events, no darks at all, empty input), threshold pinning (1.4× / 0.6×), `DARK_EVENT_TYPES` membership.
- [x] **`tests/test_watch_generate.py`** (12 tests) — JSONL ingest validation (valid line, bad JSON, schema mismatch), `--min-significance` gate (low-sig event lands in DB but skips LLM; high-sig event generates chronicles in EN+ZH for all agents), CLI argparse surface.
- [x] **Lifted `stamp_era_mood` + `DARK_EVENT_TYPES` to `chronicler.scoring`** — previously buried inside `scripts/import_dynasty.py` where it couldn't be imported by tests. Importer now calls into the shared module.
- Result: pytest 6 → **59 tests**, ~10× the coverage. All green; ruff clean.

## Phase 1 v0.1 — Royal Library in-game UI (GUI-only) ✅

First shippable mod artefact. The Royal Court window grows a fifth tab — *Royal Library* — that opens a parchment-styled overlay listing up to 30 dynastic-chronicle entries in reverse chronological order. Bilingual EN + zh-CN from day one. Merged via PR [#6](https://github.com/Americium3/vox-dynastica/pull/6).

- [x] `mod/vox-dynastica/` mod skeleton (in-mod `descriptor.mod` + user-side `vox_dynastica.mod`)
- [x] `gui/window_royal_court.gui` — full vanilla file copy + Royal Library tab button (uses `VariableSystem` toggle, not the hardcoded `SetActiveTab` enum)
- [x] `gui/window_royal_library.gui` — parchment overlay: layered backgrounds, period-appropriate `MapFont`, decorative scroll edges, divider per card, scrollbox of 30 entry slots
- [x] `gui/preload/vd_textformatting.gui` — four ink-tone inline colour tags (`color_vd_ink`, `color_vd_ink_body`, `color_vd_ink_subtitle`, `color_vd_cinnabar`)
- [x] Bilingual sample loc (6 curated entries, slots 07–30 empty placeholders)
- [x] Placeholder tab icon (`roco_library.dds`, currently a copy of `roco_grandeur`)
- [x] 8 engine constraints documented in `mod/README.md` (no partial GUI patches, MapFont fallback chain, inline colour tags only, UTF-8 BOM on loc, etc.)
- [ ] Custom tab icon to replace the placeholder (deferred to a later cosmetic pass)
- [ ] Empty-slot hiding via `on_game_start` reading `vd_entry_count` (Phase 1.2)

## Phase 1.1 — `emit-loc` CLI (LLM → CK3 loc writer) ✅

The "writer" end of the bridge between the LLM pipeline and the Royal Library's 30 hardcoded slots. Pure Python, no game-side companion yet.

- [x] **`chronicler emit-loc --mod-dir <path>` subcommand** — pulls chronicles from the DB, picks one row per event for the chosen agent/language, reverse-sorts by year, writes `localization/<folder>/vox_dynastica_l_<folder>.yml` with the required UTF-8 BOM.
- [x] **Pure `render_loc_yaml()`** — separates "format the bytes" from "decide what to render" so tests can pin engine-contract invariants without filesystem I/O.
- [x] **`LocEntry` dataclass + `collect_entries_from_store()`** — defines the projection from event-keyed / chronicle-keyed `Store` rows to entry-keyed library slots. Single point of change when the projection evolves.
- [x] **Inline colour tags wired** — year → `#color_vd_cinnabar`, title → `#color_vd_ink`, body → `#color_vd_ink_body`, matching the Phase 1 GUI contract.
- [x] **`vd_entry_count` key emitted** — gives Phase 1.2's empty-slot hider a single integer to bind against.
- [x] **28 new tests** (`tests/test_emit_loc.py`) — engine-contract pins (BOM, key shape, no tabs, reverse-chrono order, CJK round-trip, empty-slot rendering, idempotency) and Store-projection coverage (agent filter, language filter, year window, max-entries truncation, empty-chronicle skip). Total suite 59 → **87 tests**.
- [x] **`vox-companion` tray app** — landed in Phase 1.2 (see below).

## Phase 1.2 — `vox-companion` save-watcher tray app ✅

Closes the Tier-2 automation loop. The player launches the companion once; from then on every CK3 autosave triggers a pipeline run that refreshes the in-game Royal Library.

- [x] **`chronicler.companion` core module** — `CompanionConfig` (constructor-injected, no globals), `SaveWatcher` (stdlib polling with size+mtime debounce; resets on growth, fires once per stable signature, won't re-fire on pre-existing files), `run_pipeline_once()` (parse → store → generate → emit-loc) returning a frozen `RunReport` (errors caught and reported, not raised), `run_headless()` console loop.
- [x] **`chronicler.tray` optional UI** — pystray + Pillow wrapper. Tray menu: status line (read-only), Pause toggle, "Re-run on latest save" manual trigger, Open mod loc folder, Open save-games folder, Quit. Cross-platform open-folder helper (Windows `os.startfile` / macOS `open` / Linux `xdg-open`). Watcher runs on a daemon thread so the menu stays responsive.
- [x] **`chronicler companion` CLI subcommand** — `--mod-dir`, `--db`, `--save-dir` (auto-detects Paradox layout per OS), `--lang`, `--agent`, `--max-slots`, `--poll-interval`, `--stable-polls`, `--backend` (default `dry-run` — the companion **never** burns API tokens silently), `--no-tray` for headless.
- [x] **Optional dep group** — `pip install 'vox-dynastica[companion]'` pulls pystray + Pillow. Core install stays slim; CI stays display-free.
- [x] **Ironman-safe** — process only *reads* save files and only *writes* inside the mod's `localization/` folder. Never touches the save directory in write mode.
- [x] **17 new tests** (`tests/test_companion.py`) — watcher debounce under hand-driven ticks (priming behaviour, stable-polls threshold, no-refire on same sig, refire on rewrite, hold-while-growing, pause, glob filter, callback-exception isolation, missing dir, fired-paths return value), pipeline runner (writes loc + returns report, catches parse errors, skips LLM when no new events), config defaults (Windows USERPROFILE branch, POSIX fallback), `RunReport` immutability. Total suite 87 → **104 tests**.
- [ ] **Tier 1 keypress injection** — sending `reload localization` to the running CK3 process via SendInput / xdotool. Deferred to Phase 1.5; for now the player runs the console command manually after the tray balloon fires.
- [ ] **Service / autostart integration** — Windows Task Scheduler / systemd user unit packaging. Deferred until the cloud-API picker lands, since the autostart story is most useful with `--backend claude` configured.

## Phase 1.x — In-game polish + cloud-API picker

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
