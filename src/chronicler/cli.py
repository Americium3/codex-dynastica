"""Command-line interface.

Usage examples:
    chronicler import save.ck3 --db chronicle.db
    chronicler import-json parsed.json --db chronicle.db
    chronicler ingest events.jsonl --db chronicle.db
    chronicler watch events.jsonl --db chronicle.db
    chronicler generate --db chronicle.db --from 1066 --to 1200 --lang en,zh
    chronicler generate --db chronicle.db --dry-run             # no API spend
    chronicler render --db chronicle.db --out chronicle.html --lang zh
    chronicler stats --db chronicle.db

Locale: CLI messages obey CHRONICLER_LOCALE (en|zh). The global
`--locale` flag overrides for one invocation.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .agents import (  # type: ignore[attr-defined]
    AGENTS_BY_NAME,
    ClaudeClient,
    DryRunClient,
    LLMClient,
    OllamaClient,
    build_agents,
)
from .agents.base import PRICING
from .generator import generate_range
from .i18n import _, available_locales, set_locale
from .parsers.live_hook import ingest_file, watch
from .parsers.save_import import (
    RakalyNotFoundError,
    extract_events,
    parse_save,
    parse_save_json,
)
from .render import render_html
from .schema import EventType
from .storage import Store


def _make_client(args: argparse.Namespace) -> tuple[LLMClient, str | None]:
    """Return (client, model_override). model_override is non-None for
    backends whose model namespace doesn't match the built-in Anthropic
    one (currently: ollama)."""
    # Back-compat: --dry-run still works and implies backend=dry-run.
    backend = getattr(args, "backend", None) or ("dry-run" if getattr(args, "dry_run", False) else "claude")
    if backend == "dry-run":
        return DryRunClient(), None
    if backend == "ollama":
        return (
            OllamaClient(
                model=args.ollama_model,
                base_url=args.ollama_url,
            ),
            args.ollama_model,
        )
    if backend == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(_("cli.generate.no_api_key"), file=sys.stderr)
            sys.exit(2)
        return ClaudeClient(), None
    print(f"Unknown backend: {backend}", file=sys.stderr)
    sys.exit(2)


def _parse_languages(s: str) -> list[str]:
    raw = [p.strip().lower() for p in s.split(",") if p.strip()]
    out = []
    for r in raw:
        if r.startswith("zh"):
            out.append("zh")
        elif r.startswith("en"):
            out.append("en")
        else:
            print(f"Unknown language: {r}. Supported: en, zh.", file=sys.stderr)
            sys.exit(2)
    return out or ["en"]


def _cmd_import(args: argparse.Namespace) -> int:
    store = Store(args.db)
    try:
        parsed = parse_save(args.save)
    except RakalyNotFoundError:
        print(_("cli.import.rakaly_missing"), file=sys.stderr)
        return 3
    events = list(extract_events(parsed))
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.save), inserted + skipped)
    print(_("cli.import.done", inserted=inserted, skipped=skipped))
    return 0


def _cmd_import_json(args: argparse.Namespace) -> int:
    store = Store(args.db)
    parsed = parse_save_json(args.json)
    events = list(extract_events(parsed))
    inserted, skipped = store.upsert_events(events)
    store.log_import(str(args.json), inserted + skipped)
    print(_("cli.import_json.done", inserted=inserted, skipped=skipped))
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    store = Store(args.db)
    inserted = 0
    skipped = 0
    def on_event(ev):
        nonlocal inserted, skipped
        if store.upsert_event(ev):
            inserted += 1
        else:
            skipped += 1
    ingest_file(args.jsonl, on_event)
    store.log_import(str(args.jsonl), inserted + skipped)
    print(_("cli.ingest.done", inserted=inserted, skipped=skipped))
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    """Tail the live-hook JSONL.

    Phase 0.4: with ``--generate``, each accepted event is immediately
    fed through the agent pipeline, so chronicles appear as the game is
    being played — no waiting for save-game-then-import. The
    ``--min-significance`` knob keeps trivia (an obscure activity, a
    no-stakes scheme) out of the LLM call while still letting it land
    in the database.
    """
    from .scoring import significance as _significance
    store = Store(args.db)
    print(_("cli.watch.start", path=args.jsonl))

    if args.generate:
        client, model_override = _make_client(args)
        only = None
        if args.agent:
            only = [a.strip() for a in args.agent.split(",") if a.strip()]
        agents = build_agents(client, model_override=model_override, only=only)
        languages = _parse_languages(args.lang)
    else:
        agents = []
        languages = []

    def on_event(ev):
        if not store.upsert_event(ev):
            return
        print(_("cli.watch.event", event_id=ev.event_id, type=ev.type.value, year=ev.year))
        if not args.generate:
            return
        score = _significance(ev)
        if score < args.min_significance:
            print(
                f"  [skip-llm] significance={score} < threshold={args.min_significance}",
                flush=True,
            )
            return
        # Stream: one event through every active agent × every language.
        # We deliberately call render() directly rather than going through
        # generate_range() to avoid scanning the whole DB on every line.
        for agent in agents:
            for lang in languages:
                try:
                    result = agent.render(ev, language=lang)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [error] {agent.name}/{lang}: {exc}", flush=True)
                    continue
                store.save_chronicle(
                    event_id=ev.event_id,
                    agent=agent.name,
                    language=lang,
                    title=result.title,
                    body=result.body,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cached_input_tokens=result.cached_input_tokens,
                    cost_usd=result.cost_usd,
                )
                print(
                    f"  [{agent.name}/{lang}] {result.title!r}  "
                    f"({result.input_tokens}→{result.output_tokens} tok)",
                    flush=True,
                )

    try:
        watch(args.jsonl, on_event, poll_interval=args.interval)
    except KeyboardInterrupt:
        print(_("cli.watch.stopped"))
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    store = Store(args.db)
    client, model_override = _make_client(args)
    only = None
    if args.agent:
        only = [a.strip() for a in args.agent.split(",") if a.strip()]
    agents = build_agents(client, model_override=model_override, only=only)
    event_type = EventType(args.type) if args.type else None
    languages = _parse_languages(args.lang)
    stats = generate_range(
        store=store,
        agents=agents,
        from_year=args.from_year,
        to_year=args.to_year,
        event_type=event_type,
        character_id=args.character,
        languages=languages,
        force=args.force,
    )
    print(_(
        "cli.generate.summary",
        generated=stats.generated,
        skipped=stats.skipped,
        failed=stats.failed,
        input=stats.total_input_tokens,
        output=stats.total_output_tokens,
        cached=stats.total_cached_tokens,
        cost=f"{stats.total_cost_usd:.4f}",
    ))
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    store = Store(args.db)
    lang = "zh" if args.lang.startswith("zh") else "en"
    out = render_html(
        store,
        args.out,
        title=args.title,
        subtitle=args.subtitle,
        language=lang,
    )
    print(_("cli.render.done", path=out))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    store = Store(args.db)
    events = store.list_events()
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e.type.value] = by_type.get(e.type.value, 0) + 1
    print(_("cli.stats.events_header", n=len(events)))
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {t}: {n}")
    langs = store.available_languages()
    if langs:
        print(f"  languages: {', '.join(langs)}")
    print(_("cli.stats.cost_total", cost=f"{store.total_cost():.4f}"))
    print(_("cli.stats.pricing_header"))
    for model, price in PRICING.items():
        print(f"  {model}: in={price['input']:.2f} out={price['output']:.2f} cache_read={price['cache_read']:.2f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chronicler",
        description="Vox Dynastica — voice of the dynasty (Phase 0 MVP, CK3 chronicle generator).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--verbose", "-v", action="count", default=0, help="-v for INFO, -vv for DEBUG")
    p.add_argument(
        "--locale",
        choices=list(available_locales()),
        default=None,
        help="Override CHRONICLER_LOCALE for this invocation (en|zh).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("import", help="Import a CK3 .ck3 save file (requires rakaly).")
    pi.add_argument("save", type=Path)
    pi.add_argument("--db", type=Path, default="chronicle.db")
    pi.set_defaults(func=_cmd_import)

    pij = sub.add_parser(
        "import-json",
        help="Import a pre-converted save JSON (skip rakaly).",
    )
    pij.add_argument("json", type=Path)
    pij.add_argument("--db", type=Path, default="chronicle.db")
    pij.set_defaults(func=_cmd_import_json)

    ping = sub.add_parser("ingest", help="One-shot ingest of a live-hook JSONL file.")
    ping.add_argument("jsonl", type=Path)
    ping.add_argument("--db", type=Path, default="chronicle.db")
    ping.set_defaults(func=_cmd_ingest)

    pw = sub.add_parser(
        "watch",
        help="Tail a live-hook JSONL file continuously (Phase 0.4: optionally "
             "stream-generate chronicles per event).",
    )
    pw.add_argument("jsonl", type=Path)
    pw.add_argument("--db", type=Path, default="chronicle.db")
    pw.add_argument("--interval", type=float, default=1.0)
    pw.add_argument(
        "--generate",
        action="store_true",
        help="Run the agent pipeline immediately as each event arrives. "
             "Without this, watch just upserts to the DB; you'd run "
             "`chronicler generate` later.",
    )
    pw.add_argument(
        "--min-significance",
        type=int,
        default=55,
        help="Skip the LLM for events scoring below this. Event still lands "
             "in the DB. Default 55 (matches the medium scope preset).",
    )
    pw.add_argument(
        "--lang",
        default="en",
        help="Output languages for --generate. Comma-separated. Default: en.",
    )
    pw.add_argument(
        "--backend",
        choices=["claude", "ollama", "dry-run"],
        default=None,
        help="LLM backend when --generate is set.",
    )
    pw.add_argument("--ollama-model", default="gemma3:27b")
    pw.add_argument("--ollama-url", default="http://localhost:11434")
    pw.add_argument(
        "--agent",
        default=None,
        help=f"Restrict to a subset of agents (comma-separated). Known: {','.join(sorted(AGENTS_BY_NAME))}.",
    )
    pw.add_argument("--dry-run", action="store_true", help="Shortcut for --backend dry-run.")
    pw.set_defaults(func=_cmd_watch)

    pg = sub.add_parser("generate", help="Generate chronicles for stored events.")
    pg.add_argument("--db", type=Path, default="chronicle.db")
    pg.add_argument("--from", dest="from_year", type=int, default=None)
    pg.add_argument("--to", dest="to_year", type=int, default=None)
    pg.add_argument("--type", default=None, help="Filter to one event type.")
    pg.add_argument("--character", default=None, help="Filter to one primary character id.")
    pg.add_argument(
        "--lang",
        default="en",
        help="Output language(s), comma-separated. Supported: en, zh. Default: en.",
    )
    pg.add_argument("--force", action="store_true", help="Regenerate even if a chronicle already exists.")
    pg.add_argument(
        "--backend",
        choices=["claude", "ollama", "dry-run"],
        default=None,
        help="LLM backend. claude=Anthropic API, ollama=local model, dry-run=offline mock. "
             "Default: claude if ANTHROPIC_API_KEY is set, else error (or pass --dry-run).",
    )
    pg.add_argument(
        "--ollama-model",
        default="gemma3:27b",
        help="Model name when --backend=ollama. Default: gemma3:27b.",
    )
    pg.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama server URL. Default: http://localhost:11434.",
    )
    pg.add_argument(
        "--agent",
        default=None,
        help=f"Restrict to a subset of agents (comma-separated). Known: {','.join(sorted(AGENTS_BY_NAME))}.",
    )
    pg.add_argument("--dry-run", action="store_true", help="Shortcut for --backend dry-run.")
    pg.set_defaults(func=_cmd_generate)

    pr = sub.add_parser("render", help="Render stored chronicles as a static HTML page.")
    pr.add_argument("--db", type=Path, default="chronicle.db")
    pr.add_argument("--out", type=Path, default="chronicle.html")
    pr.add_argument("--title", default=None)
    pr.add_argument("--subtitle", default=None)
    pr.add_argument(
        "--lang",
        default="en",
        help="Which language's chronicles to render. Supported: en, zh. Default: en.",
    )
    pr.set_defaults(func=_cmd_render)

    ps = sub.add_parser("stats", help="Print summary of stored events and cost.")
    ps.add_argument("--db", type=Path, default="chronicle.db")
    ps.set_defaults(func=_cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.locale:
        set_locale(args.locale)
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
