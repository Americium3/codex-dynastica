# Vox Dynastica

**English** · [简体中文](README.zh-CN.md)

> Voice of the dynasty — an AI-driven **dynastic chronicle** companion for Crusader Kings 3.

CK3's biggest narrative gap is that 300 years of play produce no real *history*. Generic event text repeats. Your dynasty has no remembered past. **Vox Dynastica** uses large language models to generate living, biased, contradictory chronicles of the same events — court histories, peasant ballads, and (in later phases) enemy histories and church records — so the same war can be remembered as a holy victory in one chamber and a tax raid in another village.

## Status

- **Phase 0 — Court Historian + Peasant Ballad MVP.** ✅ done.
- **Phase 0.1 — Dynastic title-holder scope + local-model (Ollama) backend.** ✅ done.
- **Phase 0.2 — Player-selectable scope (narrow / middle / wide) + shorter chronicles.** ✅ done.
- **Phase 0.3 — Significance-based event selection + `era_mood` ballad bias + imagery library ×20.** ✅ done.
- **Phase 0.4 — Real-time event ingest via live-hook + tiered selectivity presets.** ✅ done.
- **Phase 0.5 — CI bootstrap (ruff + pytest on GitHub Actions) + test backfill (6 → 59 tests).** ✅ done (this revision).
- **Phase 1 — In-game Royal Library UI (vanilla-fidelity) + cloud-API picker (RimTalk style).** 🚧 not started.
- **Phase 2 — Enemy + Church perspectives.** 🚧 not started.
- **Phase 3 — Historical drift, physical carriers, gameplay reverse hooks.** 🚧 not started.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

## Features (Phase 0 → 0.4)

- **Save file import** — converts a `.ck3` save to events via [rakaly](https://github.com/rakaly), then extracts deaths, wars, coronations, marriages, births, and trait events.
- **Dynastic-scope extractor** — `scripts/import_dynasty.py` walks the **player's primary title** (`landed_data.domain[0]`) and pulls every event hanging off that throne: title-holder deaths, first-heir birth/death, marriages, battles, schemes, stories, artifacts, activities, and significant health/aging traits of the current holder.
- **Tiered scope presets** — `--scope {narrow,dynastic,middle,wide}` bundles *what to pull* and *how strict the cutoff is*. `narrow` is a tight family-album view (~6 events); `dynastic` / `middle` is the calibrated default (~12 events); `wide` is a world-scale chronicle (~24 events). Phase 0.4.
- **Real-time live-hook ingest** — `chronicler watch <jsonl> --db ... --generate` tails a JSONL file the running game writes, validates each line, stores it, and immediately narrates it through every agent and language. No save-game-then-import dance. `--min-significance` gates the LLM call so trivia still lands in the DB but doesn't burn tokens. See [docs/REALTIME_INGEST.md](docs/REALTIME_INGEST.md) for the CK3 mod-side contract.
- **Era-mood-aware ballads** — every event carries an `era_mood` (turbulent / ordinary / peaceful) computed from the ±15-year density of wars / deaths / disasters in the chronicle. The peasant ballad combines the event's base tone with the era weather: a birth in a turbulent decade still rejoices but admits the missing brother; a death in peacetime carries unusual weight. Phase 0.3.
- **Significance-ranked event selection** — a tag-aware scoring table (`chronicler.scoring.SIGNIFICANCE`) ranks candidate events; the chronicle keeps the top N. Used by both the save importer (post-trim) and the live-hook watcher (LLM-cost gate). Phase 0.3 + 0.4.
- **Two narrative voices** — Court Historian (sober archaic English / 半文言史笔) and Peasant Ballad (folk-Saxon / 《诗经·国风》四言), each driven by a long cached system prompt. Phase 0.3 expanded the ballad's eight-category imagery library ~20× so the singer doesn't repeat the same five words across many songs.
- **Three LLM backends** — Anthropic Claude (cloud), **Ollama local models** (e.g. `gemma3:27b`, no API key required), or DryRun mock (offline).
- **Prompt caching (Claude)** — system prompts are marked `cache_control: ephemeral`, repeat calls within the 5-minute TTL pay 10× less.
- **Cost accounting** — every chronicle row tracks input/output/cached tokens and a dollar estimate. Local models report \$0.
- **Idempotent storage** — re-importing the same save does not duplicate events; re-running `generate` skips already-chronicled `(event, agent, language)` triples unless `--force`.
- **Bilingual everything** — every user-facing surface (CLI, HTML chrome, LLM output, ROADMAP, docs) ships in **EN + zh-CN** simultaneously.
- **Static HTML output** — parchment-styled dual-column reader, opens in any browser.

## Quickstart

```bash
git clone https://github.com/Americium3/vox-dynastica.git
cd vox-dynastica
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# Smoke-test with the bundled fixture save, no API key needed:
chronicler import-json tests/fixtures/sample_save.json --db demo.db
chronicler generate --db demo.db --dry-run
chronicler render --db demo.db --out demo.html

# Local model (gemma3:27b via Ollama):
ollama pull gemma3:27b
chronicler generate --db demo.db --backend ollama --ollama-model gemma3:27b --lang en,zh
chronicler render --db demo.db --out demo_en.html --lang en
chronicler render --db demo.db --out demo_zh.html --lang zh

# Cloud (Anthropic) instead:
export ANTHROPIC_API_KEY=sk-ant-...
chronicler generate --db demo.db --backend claude --force --lang en,zh
```

### Working with a real save (dynastic scope)

```bash
# Requires rakaly; on Windows the project ships a copy in bin/rakaly.exe.
python scripts/import_dynasty.py \
    --save "C:/.../save games/MyCampaign.ck3" \
    --db campaign.db \
    --from-year 1000 --to-year 1066 \
    --max-per-type 6

chronicler generate --db campaign.db --backend ollama --ollama-model gemma3:27b --lang en,zh
chronicler render --db campaign.db --out campaign_en.html --lang en \
    --title "Chronicle of the House of Wessex"
chronicler render --db campaign.db --out campaign_zh.html --lang zh \
    --title "韦塞克斯王朝编年"
```

### Watching a live game (Phase 0.4)

The game (once the Phase 1 mod ships) writes events to `events.jsonl` via `debug_log` from `scripted_effect`. Until then you can drive the pipeline by hand: writing JSONL lines to the file is exactly what the mod will do, just slower.

```bash
# Terminal 1: tail and narrate on arrival
chronicler watch ./events.jsonl --db live.db --generate \
    --backend ollama --ollama-model gemma3:27b --lang en,zh \
    --min-significance 55

# Terminal 2: pretend to be CK3
cat >> ./events.jsonl <<'EOF'
{"event_id":"live_hook:ruler_death:1066:abc123","source":"live_hook","type":"ruler_death","year":1066,"primary_actors":[{"character_id":"42","name":"Harold","dynasty":"Godwin"}],"tags":["death_battle"]}
EOF
```

Watch terminal 1 — the event is accepted, then the Court Historian and Peasant Ballad both narrate it in EN + ZH, one LLM call per (event × agent × language). Drop `--generate` to just collect events into the DB and narrate later with `chronicler generate`. See [docs/REALTIME_INGEST.md](docs/REALTIME_INGEST.md) for the full CK3-side contract.

## Architecture

```
.ck3 save  ┐
           ├─[rakaly]→ parsed.json ─[extract]─┐
events.jsonl (live) ──[validate]─────────────┤
                                              ↓
                                           SQLite (events)
                                              │
                                  [generator + agents]
                                              │
                                           SQLite (chronicles)
                                              │
                                         [renderers]
                                              │
                                    HTML  /  (Phase 1: CK3 GUI)
```

- **[`schemas/event.schema.json`](schemas/event.schema.json)** — JSON Schema pinning the save-import / live-hook interface. The Python `ChronicleEvent` model in `src/chronicler/schema.py` mirrors it 1:1.
- **`src/chronicler/parsers/`** — save-file (`save_import.py`) and live-hook (`live_hook.py`) ingestors. Both produce `ChronicleEvent` instances.
- **`scripts/import_dynasty.py`** — the dynastic-scope importer for real saves (Phase 0.1–0.4). Honours `--scope {narrow,dynastic,middle,wide}` for tiered strictness.
- **`src/chronicler/scoring.py`** — significance table + scope presets, shared between the save importer and the live-hook watcher (Phase 0.4).
- **`src/chronicler/storage.py`** — SQLite with `events`, `chronicles`, `import_log` tables. Idempotent upserts.
- **`src/chronicler/agents/`** — one module per narrative voice. `base.py` holds the Claude wrapper, the Ollama local-model wrapper, the dry-run mock, and pricing math.
- **`src/chronicler/generator.py`** — orchestrator; iterates events × agents × languages, calls the LLM, persists results.
- **`src/chronicler/render/html.py`** — pure-Python HTML output for Phase 0.

## Configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required when `--backend claude`. |
| `CHRONICLER_LOCALE` | `en` or `zh`. Affects CLI messages and HTML chrome. CLI flag `--locale` overrides. |
| `CHRONICLER_RAKALY` | Override path to the rakaly binary. Otherwise the package looks in `<repo>/bin/rakaly[.exe]` then `$PATH`. |

Model selection per event is a heuristic in `Agent.model_for`: war/death/coronation route to the major model, everything else to the minor. The Ollama backend ignores those choices and uses its single configured local model.

## Development

```bash
pip install -e ".[dev]"
pytest                       # runs the smoke test
ruff check src tests
```

The smoke test (`tests/test_smoke.py`) exercises the full pipeline end-to-end against the bundled fixture using `DryRunClient`, so it runs in CI with no API key.

## Compatibility & limits

- Tested against CK3 save formats produced by the 1.12.x line, including ironman saves and a range of modded saves.
- Ironman binary saves require rakaly (which handles the token table for you).
- Phase 0 does not yet read schemes, artifacts, struggles, or activities — those slot in as the prompt corpus matures.
- The dynastic-scope importer assumes `landed_data.domain[0]` is the primary title (CK3's precedence convention).

## Roadmap

Detailed [phased roadmap](docs/ROADMAP.md). Short version:

- **Phase 0.2**: player-selectable chronicle scope — **narrow** (own dynastic house only), **middle** (landless-adventurer mode: lieges of any realm you've resided in), **wide** (every prominent ruler in the known world).
- **Phase 1**: in-game Royal Library window matching vanilla CK3 GUI exactly + cloud-API picker in mod settings (RimTalk-style provider/key/model selection).
- **Phase 2**: enemy historian + church chronicle. Cross-border circulation via traveler/envoy characters.
- **Phase 3**: 50-year transcription drift, library buildings as physical carriers (destructible), gameplay reverse hooks (legitimacy, popular opinion, dynasty modifiers).

## Contributing

Issues and PRs welcome — especially around save-file shape coverage (the rakaly JSON layout changes between CK3 versions) and prompt quality for the two existing voices. See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

This project is not affiliated with Paradox Interactive. Crusader Kings III is a trademark of Paradox Interactive AB.
