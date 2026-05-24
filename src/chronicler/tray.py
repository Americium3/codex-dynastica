"""System-tray wrapper around :mod:`chronicler.companion`.

Phase 1.2. This module is **optional** -- it imports ``pystray`` and
``Pillow``, which are not core dependencies. Install via:

    pip install vox-dynastica[companion]

Architecture:

    main thread  ->  pystray Icon.run()      (blocks until quit)
    bg thread    ->  SaveWatcher.run_forever()

The watcher runs in a daemon thread so Ctrl-C / "Quit" from the tray
menu can shut the process down cleanly. State shared between the two
threads is the ``CompanionState`` mailbox, which the menu reads to
decide checkbox state ("Paused", last status text, etc.).

Tests live in :mod:`tests.test_companion` and only cover the headless
side; this module is integration-tested by hand because pystray needs a
display.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .companion import CompanionConfig, RunReport, SaveWatcher, run_pipeline_once

logger = logging.getLogger(__name__)


@dataclass
class CompanionState:
    """Mailbox between the watcher thread and the tray menu callbacks.

    All mutations happen on the watcher thread; the menu reads opportunistically
    (pystray polls these for menu-item state on every menu open, so we don't
    bother locking -- worst case a menu shows a slightly stale tooltip).
    """

    last_report: RunReport | None = None
    runs_total: int = 0
    runs_failed: int = 0
    history: list[RunReport] = field(default_factory=list)
    history_max: int = 20

    def push(self, report: RunReport) -> None:
        self.last_report = report
        self.runs_total += 1
        if not report.ok:
            self.runs_failed += 1
        self.history.append(report)
        if len(self.history) > self.history_max:
            self.history = self.history[-self.history_max :]

    def tooltip(self) -> str:
        if self.last_report is None:
            return "Vox Dynastica companion -- waiting for first save"
        r = self.last_report
        if r.ok:
            return (
                f"Vox Dynastica -- last: {r.save_path.name} "
                f"(+{r.events_new} ev / {r.chronicles_generated} ch). "
                f"Runs: {self.runs_total} ({self.runs_failed} failed)."
            )
        return (
            f"Vox Dynastica -- last: {r.save_path.name} FAILED ({r.error}). "
            f"Runs: {self.runs_total} ({self.runs_failed} failed)."
        )


def _make_icon_image(size: int = 64):
    """A 64x64 cinnabar-ink monogram so the tray icon doesn't look like a
    blank square. Kept inline (no PNG asset) so the optional dep tree
    stays at just pystray + Pillow."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Parchment circle.
    d.ellipse((2, 2, size - 2, size - 2), fill=(237, 217, 168, 255))
    # Cinnabar VD initials.
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover -- defensive
        font = None
    d.text((size * 0.22, size * 0.30), "VD", fill=(140, 38, 25, 255), font=font)
    return img


def _open_folder(path: Path) -> None:
    """Cross-platform "show in file manager"."""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
    except Exception:  # noqa: BLE001
        logger.exception("could not open %s", path)


def run_tray(config: CompanionConfig) -> None:
    """Launch the tray UI. Blocks until the user picks Quit.

    Raises :class:`ImportError` if pystray / Pillow aren't installed --
    callers (CLI) should catch and print an install hint rather than
    letting the traceback hit the user.
    """
    try:
        import pystray
    except ImportError as exc:  # pragma: no cover -- exercised by the CLI fallback
        raise ImportError(
            "vox-companion tray UI needs pystray + Pillow. Install via:\n"
            "    pip install 'vox-dynastica[companion]'\n"
            "Or run headless:  chronicler companion --no-tray"
        ) from exc

    state = CompanionState()

    def on_report(r: RunReport) -> None:
        state.push(r)
        icon.title = state.tooltip()  # noqa: F821 -- icon defined below
        # pystray notification is best-effort; on some Linux WMs it's a no-op.
        try:
            if r.ok:
                icon.notify(  # noqa: F821
                    f"+{r.events_new} events, {r.chronicles_generated} chronicles. "
                    f"Run `reload localization` in-game to see them.",
                    "Vox Dynastica -- library updated",
                )
            else:
                icon.notify(  # noqa: F821
                    r.error or "see log",
                    "Vox Dynastica -- pipeline failed",
                )
        except Exception:  # noqa: BLE001
            logger.exception("tray notify failed")

    def handle_path(path: Path) -> None:
        report = run_pipeline_once(path, config)
        on_report(report)

    watcher = SaveWatcher(
        config.save_dir,
        handle_path,
        poll_interval=config.poll_interval,
        stable_polls=config.stable_polls,
        file_glob=config.file_glob,
    )
    watcher.prime()

    # ----- menu actions -----

    def toggle_pause(icon, item):  # noqa: ARG001 -- pystray signature
        watcher.paused = not watcher.paused
        icon.title = (
            "Vox Dynastica -- PAUSED" if watcher.paused else state.tooltip()
        )

    def open_mod_loc(icon, item):  # noqa: ARG001
        _open_folder(config.mod_dir / "localization")

    def open_save_dir(icon, item):  # noqa: ARG001
        _open_folder(config.save_dir)

    def rerun_latest(icon, item):  # noqa: ARG001
        # Manual trigger: pick the newest save in the directory and re-run,
        # regardless of whether we've fired on it before. Useful when the
        # player wants to force a refresh after editing the prompt.
        candidates = sorted(
            config.save_dir.glob(config.file_glob),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if not candidates:
            return
        threading.Thread(target=handle_path, args=(candidates[0],), daemon=True).start()

    def quit_app(icon, item):  # noqa: ARG001
        watcher.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(
            lambda item: state.tooltip(),  # noqa: ARG005 -- pystray dynamic-label form
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Pause", toggle_pause, checked=lambda item: watcher.paused  # noqa: ARG005
        ),
        pystray.MenuItem("Re-run on latest save", rerun_latest),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open mod localization folder", open_mod_loc),
        pystray.MenuItem("Open save-games folder", open_save_dir),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )

    icon = pystray.Icon(
        "vox-dynastica",
        _make_icon_image(),
        "Vox Dynastica -- waiting for first save",
        menu,
    )

    def watcher_thread() -> None:
        watcher.run_forever()

    threading.Thread(target=watcher_thread, name="vox-watcher", daemon=True).start()
    icon.run()
