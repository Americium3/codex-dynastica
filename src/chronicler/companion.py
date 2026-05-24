"""vox-companion — Tier-2 save-watcher that auto-refreshes the Royal Library.

Phase 1.2. Sits between CK3 and the Phase 1.1 ``emit-loc`` CLI:

    CK3 autosave -> SaveWatcher detects -> run_pipeline_once()
                       |                        |
                       v                        v
                  debounce (size+mtime    parse_save -> upsert ->
                  stable across N polls)   generate -> write_mod_loc

The tray UI (:mod:`chronicler.tray`) is a thin wrapper around this module
that adds a system-tray icon + menu. Importantly, ``companion`` itself has
**zero** GUI dependencies -- pystray / pillow are optional extras, so the
core watcher + runner can be tested headlessly on CI without a display.

Design notes worth not forgetting:

*   **Why polling, not ``watchdog``.** CK3 writes save games as multi-MB
    binary blobs over several seconds; the OS-level "file modified" event
    fires repeatedly during the write. We'd just rebuild the debounce
    layer on top of it anyway. Polling stdlib ``os.stat`` is simpler and
    keeps the dep tree pure-Python.
*   **Why we don't parse in the watcher tick.** Rakaly + LLM calls can
    take 10-60 s; blocking the watcher would miss subsequent saves. The
    watcher's ``on_stable`` callback hands the path off; the caller picks
    threading vs. queueing.
*   **Ironman safety.** This process only *reads* save files and *writes*
    inside the mod's localization folder -- it never touches the game's
    save directory in write mode. Safe to leave running during ironman
    sessions (the in-game refresh still requires the player to restart
    CK3 or run ``reload localization`` in non-ironman debug; that's a
    Phase 1.5 keypress-injection problem).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .emit_loc import collect_entries_from_store, write_mod_loc
from .storage import Store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- config


@dataclass
class CompanionConfig:
    """Runtime configuration. Everything is constructor-injected so tests
    don't have to monkey-patch a global.

    Default ``save_dir`` matches the standard Paradox install layout on
    Windows; on macOS / Linux the caller must override.
    """

    mod_dir: Path
    db_path: Path
    save_dir: Path
    languages: list[str] = field(default_factory=lambda: ["en", "zh"])
    agent: str = "court_historian"
    max_slots: int = 30
    # Debounce knobs. ``poll_interval`` is the watcher tick; ``stable_polls``
    # is how many consecutive ticks a file's (size, mtime) must remain
    # unchanged before we treat the write as complete.
    poll_interval: float = 2.0
    stable_polls: int = 2
    # Only react to files whose name matches one of these patterns. CK3's
    # autosave is literally "autosave.ck3"; named manual saves are arbitrary
    # but always end in ``.ck3``. Default = all ``.ck3``.
    file_glob: str = "*.ck3"
    # ``backend``: 'claude' / 'ollama' / 'dry-run'. dry-run is the default
    # because Tier 2 must *never* burn API tokens without the user opting
    # in -- silent background processes spending money is a hostile pattern.
    backend: Literal["claude", "ollama", "dry-run"] = "dry-run"
    ollama_model: str = "gemma3:27b"
    ollama_url: str = "http://localhost:11434"

    @classmethod
    def default_save_dir(cls, *, os_name: str | None = None) -> Path:
        """Best-guess Paradox save-games directory on the current OS.

        Windows: ``%USERPROFILE%/Documents/Paradox Interactive/Crusader Kings III/save games``
        Other:   ``~/.local/share/Paradox Interactive/Crusader Kings III/save games``
        (Wine layout; native macOS/Linux ports don't exist for CK3.)

        ``os_name`` is an explicit override (mirrors ``os.name``) so tests
        can exercise both branches without monkeypatching the global -- which
        would break pytest's own ``Path`` machinery on Windows.
        """
        name = os_name if os_name is not None else os.name
        if name == "nt":
            base = Path(os.environ.get("USERPROFILE", str(Path.home())))
            return base / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "save games"
        return (
            Path.home()
            / ".local" / "share" / "Paradox Interactive"
            / "Crusader Kings III" / "save games"
        )


# ---------------------------------------------------------------- watcher


@dataclass(frozen=True)
class _FileSig:
    """Compact (size, mtime_ns) tuple. Frozen so it can live in a dict."""

    size: int
    mtime_ns: int


class SaveWatcher:
    """Polls ``save_dir`` and fires ``on_stable(path)`` exactly once per
    save once that save has finished being written.

    The watcher keeps two pieces of per-file state:

    *   ``_pending``: (sig, consecutive_stable_count) for files currently
        being observed. Resets when sig changes (file still being written).
    *   ``_fired``: signatures we've already handed off, so a save that
        sits in the directory for hours doesn't re-fire on every tick.

    On startup, every existing file is recorded in ``_fired`` at its
    current signature -- we only want to react to *new* writes, not to
    every save that happens to already be on disk when we launch.
    """

    def __init__(
        self,
        save_dir: Path,
        on_stable: Callable[[Path], None],
        *,
        poll_interval: float = 2.0,
        stable_polls: int = 2,
        file_glob: str = "*.ck3",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if stable_polls < 1:
            raise ValueError("stable_polls must be >= 1")
        self.save_dir = save_dir
        self.on_stable = on_stable
        self.poll_interval = poll_interval
        self.stable_polls = stable_polls
        self.file_glob = file_glob
        self._clock = clock
        self._sleep = sleep
        self._pending: dict[Path, tuple[_FileSig, int]] = {}
        self._fired: dict[Path, _FileSig] = {}
        self._stopped = False
        self.paused = False

    # ----- testable single-step API -----

    def prime(self) -> None:
        """Record current contents as already-fired. Call once at startup
        so we don't re-narrate every save that was sitting on disk before
        the companion launched."""
        for p in self._scan():
            sig = self._sig(p)
            if sig is not None:
                self._fired[p] = sig

    def tick(self) -> list[Path]:
        """One scan + debounce cycle. Returns the paths that became stable
        on this tick (the callback has already been invoked for each).

        Returning the list (instead of only firing the callback) makes the
        watcher's behaviour pinnable in tests without a mock callback.
        """
        if self.paused:
            return []
        fired_now: list[Path] = []
        seen: set[Path] = set()
        for path in self._scan():
            seen.add(path)
            sig = self._sig(path)
            if sig is None:
                continue
            # Already handed off at this exact sig? Skip.
            if self._fired.get(path) == sig:
                continue
            prev = self._pending.get(path)
            if prev is None or prev[0] != sig:
                # Either brand-new or still being written (sig changed).
                count = 1
            else:
                # Same sig as last tick -> increment stable counter.
                count = prev[1] + 1
            if count >= self.stable_polls:
                # Stable! Fire and remember.
                self._fired[path] = sig
                self._pending.pop(path, None)
                fired_now.append(path)
            else:
                self._pending[path] = (sig, count)
        # Garbage-collect pending entries for files that vanished mid-write.
        for missing in [p for p in self._pending if p not in seen]:
            self._pending.pop(missing, None)
        for path in fired_now:
            try:
                self.on_stable(path)
            except Exception:  # noqa: BLE001 -- one bad callback shouldn't kill the watcher
                logger.exception("on_stable callback failed for %s", path)
        return fired_now

    # ----- long-running loop -----

    def run_forever(self) -> None:
        """Block until :meth:`stop` is called from another thread."""
        while not self._stopped:
            self.tick()
            self._sleep(self.poll_interval)

    def stop(self) -> None:
        self._stopped = True

    # ----- helpers -----

    def _scan(self) -> list[Path]:
        if not self.save_dir.exists():
            return []
        return sorted(self.save_dir.glob(self.file_glob))

    @staticmethod
    def _sig(path: Path) -> _FileSig | None:
        try:
            st = path.stat()
        except OSError:
            # File deleted between glob and stat -- treat as gone.
            return None
        return _FileSig(size=st.st_size, mtime_ns=st.st_mtime_ns)


# ---------------------------------------------------------------- runner


@dataclass(frozen=True)
class RunReport:
    """Outcome of one ``run_pipeline_once`` call. Returned (not just logged)
    so the tray UI can show a meaningful balloon and tests can assert on it.
    """

    save_path: Path
    events_new: int
    events_skipped: int
    chronicles_generated: int
    loc_files_written: list[Path]
    ok: bool
    error: str | None = None


def run_pipeline_once(
    save_path: Path,
    config: CompanionConfig,
    *,
    # All four are injectable so tests can substitute lightweight fakes
    # without standing up rakaly / Anthropic.
    parse_save_fn: Callable | None = None,
    extract_events_fn: Callable | None = None,
    generate_range_fn: Callable | None = None,
    make_agents_fn: Callable | None = None,
) -> RunReport:
    """Run save -> store -> generate -> emit-loc once for a single save.

    Catches and reports any exception in ``error`` rather than raising;
    a tray app should keep running even when one pipeline run fails (the
    save might be from a different mod, or the LLM backend might be down).
    """
    try:
        from .parsers.save_import import extract_events as _extract
        from .parsers.save_import import parse_save as _parse

        parse_save_fn = parse_save_fn or _parse
        extract_events_fn = extract_events_fn or _extract

        parsed = parse_save_fn(save_path)
        events = list(extract_events_fn(parsed))
        store = Store(config.db_path)
        inserted, skipped = store.upsert_events(events)

        gen_count = 0
        if inserted > 0:
            if generate_range_fn is None:
                from .generator import (
                    generate_range as generate_range_fn,  # type: ignore[assignment]
                )
            if make_agents_fn is None:
                make_agents_fn = _default_make_agents
            client, model_override = make_agents_fn(config)
            from .agents import build_agents

            agents = build_agents(client, model_override=model_override)
            stats = generate_range_fn(
                store=store,
                agents=agents,
                languages=config.languages,
            )
            gen_count = stats.generated

        written: dict[str, Path] = {}
        for lang in config.languages:
            entries = collect_entries_from_store(
                store,
                agent=config.agent,
                language=lang,
                max_entries=config.max_slots,
            )
            paths = write_mod_loc(
                config.mod_dir,
                entries,
                [lang],
                max_slots=config.max_slots,
            )
            written.update(paths)

        return RunReport(
            save_path=save_path,
            events_new=inserted,
            events_skipped=skipped,
            chronicles_generated=gen_count,
            loc_files_written=list(written.values()),
            ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("pipeline failed for %s", save_path)
        return RunReport(
            save_path=save_path,
            events_new=0,
            events_skipped=0,
            chronicles_generated=0,
            loc_files_written=[],
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def _default_make_agents(config: CompanionConfig):
    """Build the LLM client per config.backend. Mirrors cli._make_client
    but doesn't sys.exit on missing API key -- tray app should surface the
    error to the user, not nuke itself."""
    from .agents import ClaudeClient, DryRunClient, OllamaClient

    if config.backend == "dry-run":
        return DryRunClient(), None
    if config.backend == "ollama":
        return (
            OllamaClient(model=config.ollama_model, base_url=config.ollama_url),
            config.ollama_model,
        )
    if config.backend == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "backend=claude but ANTHROPIC_API_KEY is unset. "
                "Set it in the environment the companion runs in, or switch to "
                "backend=dry-run / backend=ollama."
            )
        return ClaudeClient(), None
    raise ValueError(f"Unknown backend: {config.backend}")


# ---------------------------------------------------------------- headless


def run_headless(
    config: CompanionConfig,
    *,
    on_report: Callable[[RunReport], None] | None = None,
) -> None:
    """No-tray loop: prime the watcher, then poll forever, printing each
    run's outcome. Used both as a CLI subcommand backend and as the test
    harness for the watcher under real wall-clock time.

    ``on_report`` is invoked after each pipeline run -- the tray module
    uses it to update the icon tooltip + post a balloon. CLI passes None
    (falls back to stdout)."""
    def _default_on_report(r: RunReport) -> None:
        if r.ok:
            print(
                f"[companion] {r.save_path.name}: "
                f"+{r.events_new} events, {r.chronicles_generated} chronicles, "
                f"{len(r.loc_files_written)} loc files written"
            )
        else:
            print(
                f"[companion] {r.save_path.name}: FAILED -- {r.error}",
            )

    on_report = on_report or _default_on_report

    def handle(path: Path) -> None:
        report = run_pipeline_once(path, config)
        on_report(report)

    watcher = SaveWatcher(
        config.save_dir,
        handle,
        poll_interval=config.poll_interval,
        stable_polls=config.stable_polls,
        file_glob=config.file_glob,
    )
    watcher.prime()
    print(
        f"[companion] watching {config.save_dir} "
        f"(poll={config.poll_interval}s, stable_polls={config.stable_polls}, "
        f"backend={config.backend}); Ctrl-C to stop"
    )
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        watcher.stop()
        print("\n[companion] stopped")
