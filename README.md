# CK3 AI Chronicler

> An AI-driven multi-perspective historiography companion for Crusader Kings 3.

CK3's biggest narrative gap is that 300 years of play produce no real *history*. Generic event text repeats. Your dynasty has no remembered past. **CK3 AI Chronicler** uses large language models to generate living, biased, contradictory chronicles of the same events — court histories, peasant ballads, and (in later phases) enemy histories and church records — so that the same war can be remembered as a holy victory in one chamber and a tax raid in another village.

This repository hosts **Phase 0**: the MVP pipeline. It reads CK3 save files (or live event logs), generates two narrative voices using the Claude API, and outputs a parchment-styled HTML chronicle. Later phases add an in-game GUI, more voices, generational drift, and gameplay hooks.

## Status

**Phase 0 — Court Historian + Peasant Ballad.** ✅ MVP.
**Phase 1 — In-game Royal Library UI (vanilla-fidelity).** 🚧 not started.
**Phase 2 — Enemy + Church perspectives.** 🚧 not started.
**Phase 3 — Historical drift, physical carriers, gameplay reverse hooks.** 🚧 not started.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full plan.

## Features (Phase 0)

- **Save file import** — convert a `.ck3` save to events via [rakaly](https://github.com/rakaly), then extract deaths, wars, coronations, marriages.
- **Live JSONL ingest** — tail events written by a CK3-side hook script (mod side to follow in Phase 1).
- **Two narrative voices** — Latinate Court Historian and folk Peasant Ballad, each driven by a long cached system prompt.
- **Prompt caching** — system prompts are marked `cache_control: ephemeral`, so repeat calls within the 5-minute TTL pay 10× less.
- **Cost accounting** — every chronicle row tracks input/output/cached tokens and a dollar estimate.
- **Idempotent storage** — re-importing the same save does not duplicate events; re-running `generate` skips already-chronicled (event, agent) pairs unless `--force`.
- **Static HTML output** — parchment-styled dual-column reader, opens in any browser. No web framework dependency.
- **Dry-run mode** — develop and test the entire pipeline with a mock LLM that costs $0.

## Quickstart

```bash
git clone https://github.com/USER/ck3-ai-chronicler.git
cd ck3-ai-chronicler
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# Smoke-test with the bundled fixture save, no API key needed:
chronicler import-json tests/fixtures/sample_save.json --db demo.db
chronicler generate --db demo.db --dry-run
chronicler render --db demo.db --out demo.html
# open demo.html in your browser

# Now do it for real with Claude:
export ANTHROPIC_API_KEY=sk-ant-...
chronicler generate --db demo.db --force
chronicler render --db demo.db --out demo.html
```

### Working with a real save

```bash
# Requires rakaly on PATH: https://github.com/rakaly
chronicler import "~/Documents/Paradox Interactive/Crusader Kings III/save games/MyCampaign.ck3" --db campaign.db
chronicler generate --db campaign.db --from 1066 --to 1200
chronicler render --db campaign.db --out campaign.html --title "Chronicles of the House of Wessex"
```

If you'd rather not depend on rakaly, melt the save yourself and pass the JSON:

```bash
rakaly json MyCampaign.ck3 > MyCampaign.json
chronicler import-json MyCampaign.json --db campaign.db
```

### Watching a live game

Once the in-game mod side lands (Phase 1), it will write events to `events.jsonl`. Until then you can test with the bundled fixture:

```bash
chronicler watch tests/fixtures/sample_events.jsonl --db live.db
# in another terminal:
chronicler generate --db live.db
```

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

- **[`schemas/event.schema.json`](schemas/event.schema.json)** — the JSON Schema that pins the interface between save-import and live-hook. The Python `ChronicleEvent` model in `src/chronicler/schema.py` mirrors it 1:1.
- **`src/chronicler/parsers/`** — save-file (`save_import.py`) and live-hook (`live_hook.py`) ingestors. Both produce `ChronicleEvent` instances.
- **`src/chronicler/storage.py`** — SQLite with `events`, `chronicles`, `import_log` tables. Idempotent upserts.
- **`src/chronicler/agents/`** — one module per narrative voice. `base.py` holds the Claude wrapper, the dry-run mock, and pricing math.
- **`src/chronicler/generator.py`** — orchestrator; iterates events × agents, calls the LLM, persists results.
- **`src/chronicler/render/html.py`** — pure-Python HTML output for Phase 0.

## Configuration

Settings live in environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for non-dry-run generation. |

Model selection per event is currently a heuristic in `Agent.model_for`: war/death/coronation use `claude-opus-4-7`, everything else uses `claude-haiku-4-5-20251001`. Update `PRICING` in `agents/base.py` when Anthropic publishes new rates.

## Development

```bash
pip install -e ".[dev]"
pytest                       # runs the smoke test
ruff check src tests
```

The smoke test (`tests/test_smoke.py`) exercises the full pipeline end-to-end against the bundled fixture using `DryRunClient`, so it runs in CI with no API key.

## Compatibility & limits

- Tested against CK3 save formats produced by the 1.12.x line. Older or much newer saves may use slightly different JSON shapes; the parser is intentionally tolerant and will skip unfamiliar sections.
- Ironman binary saves require rakaly (which handles the token table for you).
- Phase 0 does not yet read schemes, artifacts, struggles, or activities. These slot in as the prompt corpus matures.

## Roadmap

Detailed [phased roadmap](docs/ROADMAP.md). Short version:

- **Phase 1**: in-game Royal Library window matching vanilla CK3 GUI exactly. Localization-driven; reuses vanilla `.gfx` and templates.
- **Phase 2**: enemy historian + church chronicle. Cross-border circulation via traveler/envoy characters.
- **Phase 3**: 50-year transcription drift, library buildings as physical carriers (destructible), gameplay reverse hooks (legitimacy, popular opinion, dynasty modifiers).

## Contributing

Issues and PRs welcome — especially around save-file shape coverage (the rakaly JSON layout changes between CK3 versions) and prompt quality for the two existing voices. See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

This project is not affiliated with Paradox Interactive. Crusader Kings III is a trademark of Paradox Interactive AB.
