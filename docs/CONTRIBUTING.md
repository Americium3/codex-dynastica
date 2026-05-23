# Contributing

Phase 0 is a small Python package with a clear surface. The most valuable contributions right now are:

1. **Save-file shape coverage.** The `rakaly` JSON layout shifts between CK3 versions and partly between mods. `src/chronicler/parsers/save_import.py` extracts defensively but inevitably misses keys. If you have a save where the parser misses obvious events, please attach a redacted JSON dump and we'll add the keys.

2. **Prompt quality.** The two voices in `src/chronicler/agents/court_historian.py` and `src/chronicler/agents/peasant_ballad.py` are first drafts. Side-by-side comparisons of model output before/after a prompt tweak (saved as HTML pages) are the easiest way to argue for a change.

3. **New voices.** Phase 2 wants enemy historian and church chronicle; if you want a head start, drop a `src/chronicler/agents/<voice>.py` subclassing `Agent` and we'll review.

## Workflow

```bash
git clone https://github.com/EndingEra/codex-dynastica.git
cd ck3-ai-chronicler
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

Open a draft PR early. Reference [docs/ROADMAP.md](ROADMAP.md) so we don't accidentally re-do work.

## Style

- Type hints everywhere.
- Pydantic models for anything that crosses a boundary.
- No dependencies beyond `pydantic` + `anthropic` in the runtime. Dev/test deps go in the `dev` extras.
- Public functions get a one-line docstring; tricky internals get a short paragraph explaining *why*, not *what*.

## Tests

The smoke test in `tests/test_smoke.py` runs the full pipeline against fixture data using `DryRunClient`. Add new tests in the same file or split them out when the suite grows beyond ~200 lines.
