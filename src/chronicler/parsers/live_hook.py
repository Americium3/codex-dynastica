"""Live-hook JSONL watcher.

The CK3 mod side writes one JSON object per line into `events.jsonl` via
`log_event` from CK3 script. This module:

1. Reads/tails the file
2. Validates each line against ChronicleEvent
3. Pushes accepted events to the storage layer

The mod-side JSONL must already be in the canonical ChronicleEvent shape
(or close — we normalize a few fields). Keeping the mod side cheap means
no schema translation on the game side.

Both one-shot ingest (`ingest_file`) and continuous tailing (`watch`)
are supported.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from pydantic import ValidationError

from ..schema import ChronicleEvent, Source

log = logging.getLogger(__name__)


def iter_events_from_file(path: str | Path) -> Iterator[ChronicleEvent]:
    """Read a JSONL file once and yield valid ChronicleEvents."""
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("%s:%d invalid JSON: %s", p, lineno, e)
                continue
            data.setdefault("source", Source.LIVE_HOOK.value)
            try:
                yield ChronicleEvent.model_validate(data)
            except ValidationError as e:
                log.warning("%s:%d schema mismatch: %s", p, lineno, e.errors()[:1])
                continue


def ingest_file(
    path: str | Path,
    on_event: Callable[[ChronicleEvent], None],
) -> int:
    """One-shot ingest. Returns count of successfully parsed events."""
    count = 0
    for ev in iter_events_from_file(path):
        on_event(ev)
        count += 1
    return count


def watch(
    path: str | Path,
    on_event: Callable[[ChronicleEvent], None],
    *,
    poll_interval: float = 1.0,
    stop_after: float | None = None,
) -> None:
    """Tail `path` indefinitely (or until `stop_after` seconds elapse).

    Implementation notes:
    - We use a simple offset-based poller rather than watchdog/inotify so
      the module has zero external dependencies for Phase 0.
    - Truncation (the game starts a fresh log) is detected via file size
      shrinking, in which case we reset the read offset.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch()

    offset = 0
    started = time.monotonic()
    while True:
        if stop_after is not None and (time.monotonic() - started) >= stop_after:
            return
        try:
            size = p.stat().st_size
            if size < offset:
                log.info("Detected truncation of %s — resetting offset.", p)
                offset = 0
            if size > offset:
                with p.open("r", encoding="utf-8") as f:
                    f.seek(offset)
                    for raw in f:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError as e:
                            log.warning("invalid JSON: %s", e)
                            continue
                        data.setdefault("source", Source.LIVE_HOOK.value)
                        try:
                            ev = ChronicleEvent.model_validate(data)
                        except ValidationError as e:
                            log.warning("schema mismatch: %s", e.errors()[:1])
                            continue
                        on_event(ev)
                    offset = f.tell()
        except FileNotFoundError:
            pass
        time.sleep(poll_interval)
