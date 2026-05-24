"""Emit Vox Dynastica CK3-mod localization YAML from stored chronicles.

Phase 1.1. The in-game Royal Library (shipped in Phase 1) has 30 hardcoded
slots (`vd_entry_01_*` .. `vd_entry_30_*`). This module is the "writer" end
of the bridge between the LLM pipeline and those slots: it pulls chronicles
from the SQLite store, picks the most recent N, and writes
`localization/<lang>/vox_dynastica_l_<lang>.yml` in the exact format CK3's
localization parser demands.

Hard engine constraints (all learned the hard way in Phase 1):

1.  **UTF-8 BOM is mandatory.** Without it, CK3 silently corrupts every
    non-ASCII byte (every Chinese character becomes mojibake).
2.  **First line is the namespace marker** -- ``l_english:`` or
    ``l_simp_chinese:`` -- and child keys are indented with a *single space*
    (tabs break the parser).
3.  **Key format is ``<key>:0 "<value>"``.** The ``:0`` is a version number;
    the double quotes are required even for empty strings.
4.  **Unused slots must be emitted as empty strings, not omitted.** Otherwise
    the engine falls back to whatever was loaded last session (typically the
    Phase 1 sample entries), so an old chronicle "bleeds through" when the
    new one has fewer entries.
5.  **Slot 01 = newest entry**, slot 30 = oldest -- reverse chronological,
    matching the GUI render order (top of the parchment = freshest event).
6.  **Inline color tags** wrap every visible field, using the four tokens
    defined in ``gui/preload/vd_textformatting.gui``:
    year -> ``#color_vd_cinnabar``,
    title -> ``#color_vd_ink``,
    body -> ``#color_vd_ink_body``.
7.  **``vd_entry_count`` is emitted as the final key** -- a numeric string
    that Phase 1.2's ``on_game_start`` effect will read into VariableSystem
    so empty slots can be hidden via a binding instead of rendered blank.

The CLI subcommand ``chronicler emit-loc`` is the user surface; pure
rendering lives in :func:`render_loc_yaml` so the tests can pin behaviour
without filesystem I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage import Store

# Maximum slots the Phase 1 GUI hardcodes. Increasing this requires also
# adding slots to ``gui/window_royal_library.gui`` and to both loc YAMLs --
# the writer alone cannot grow the library.
MAX_SLOTS_DEFAULT = 30

# Language code -> (folder name, loc namespace tag). The folder name must
# match a CK3 ``localization/<dir>/`` directory and the namespace tag is the
# top-of-file marker the parser keys off.
LANG_TABLE: dict[str, tuple[str, str]] = {
    "en": ("english", "l_english"),
    "zh": ("simp_chinese", "l_simp_chinese"),
}

# Inline color tags, defined in gui/preload/vd_textformatting.gui. Centralised
# here so a colour rename is a one-line change.
COLOR_YEAR = "color_vd_cinnabar"
COLOR_TITLE = "color_vd_ink"
COLOR_BODY = "color_vd_ink_body"


@dataclass(frozen=True)
class LocEntry:
    """One library entry destined for a single ``vd_entry_NN_*`` slot.

    ``year`` is an int rather than a string so the writer can format it
    consistently and the caller can't accidentally embed colour tags or
    stray whitespace. ``title`` and ``body`` are plain text -- the writer
    wraps them in colour tags and YAML-escapes them.
    """

    year: int
    title: str
    body: str


def _yaml_escape(s: str) -> str:
    """Escape a string for the CK3 double-quoted loc value form.

    CK3's loc lexer recognises the C-style escapes ``\\\\``, ``\\"`` and
    ``\\n``. Everything else is passed through verbatim, so we keep this
    minimal -- over-escaping (e.g. encoding ``'`` or ``#``) would break the
    inline ``#color_*`` tags that wrap our content.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _wrap_color(token: str, text: str) -> str:
    """Wrap ``text`` in an inline CK3 colour tag. Empty text -> empty
    string (don't emit a colour-only tag, which would render as a stray
    ``#!``)."""
    if not text:
        return ""
    return f"#{token} {text}#!"


def render_loc_yaml(
    entries: list[LocEntry],
    lang: str,
    *,
    max_slots: int = MAX_SLOTS_DEFAULT,
    include_header: bool = True,
) -> str:
    """Render the full loc YAML body for one language.

    ``entries`` must already be in reverse-chronological order (newest
    first); this function does not re-sort. Entries beyond ``max_slots``
    are dropped silently -- the caller decides whether to log that.

    The output is a single string (no trailing newline beyond the final
    key line); callers writing to disk are responsible for prepending the
    UTF-8 BOM via :func:`write_mod_loc`.
    """
    if lang not in LANG_TABLE:
        raise ValueError(
            f"Unsupported lang {lang!r}; supported: {sorted(LANG_TABLE)}"
        )
    _, namespace = LANG_TABLE[lang]
    kept = entries[:max_slots]
    lines: list[str] = [f"{namespace}:"]
    if include_header:
        lines.extend(
            [
                " # ============================================================",
                " # Vox Dynastica -- Royal Library (auto-generated by emit-loc)",
                " # DO NOT EDIT BY HAND. Regenerate with:",
                " #   chronicler emit-loc --db <db> --mod-dir <mod>",
                " # Slot 01 = newest entry, slot 30 = oldest (reverse chrono).",
                " # ============================================================",
            ]
        )
    for i in range(1, max_slots + 1):
        slot = f"{i:02d}"
        if i <= len(kept):
            e = kept[i - 1]
            year_val = _yaml_escape(_wrap_color(COLOR_YEAR, str(e.year)))
            title_val = _yaml_escape(_wrap_color(COLOR_TITLE, e.title))
            body_val = _yaml_escape(_wrap_color(COLOR_BODY, e.body))
        else:
            year_val = title_val = body_val = ""
        lines.append(f' vd_entry_{slot}_year:0 "{year_val}"')
        lines.append(f' vd_entry_{slot}_title:0 "{title_val}"')
        lines.append(f' vd_entry_{slot}_body:0 "{body_val}"')
    # Count key for Phase 1.2 visibility binding. We export the *actual*
    # written count, not max_slots, so the GUI can hide trailing empties
    # without re-counting strings at runtime.
    lines.append(f' vd_entry_count:0 "{len(kept)}"')
    return "\n".join(lines) + "\n"


def write_mod_loc(
    mod_dir: Path,
    entries: list[LocEntry],
    languages: list[str],
    *,
    max_slots: int = MAX_SLOTS_DEFAULT,
) -> dict[str, Path]:
    """Write ``vox_dynastica_l_<lang>.yml`` for each requested language.

    Returns a ``{lang: path}`` map of the files written. Always writes with
    a UTF-8 BOM (constraint #1 above) -- the BOM is what makes CK3 trust
    the file as UTF-8 instead of falling back to the OS code page.
    """
    written: dict[str, Path] = {}
    for lang in languages:
        if lang not in LANG_TABLE:
            raise ValueError(
                f"Unsupported lang {lang!r}; supported: {sorted(LANG_TABLE)}"
            )
        folder, _ns = LANG_TABLE[lang]
        out_dir = mod_dir / "localization" / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"vox_dynastica_l_{folder}.yml"
        body = render_loc_yaml(entries, lang, max_slots=max_slots)
        # CK3 requires UTF-8 BOM. Write bytes directly rather than relying
        # on ``encoding='utf-8-sig'`` so the behaviour is identical across
        # Python versions and explicit in the test fixtures.
        out_path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        written[lang] = out_path
    return written


def collect_entries_from_store(
    store: Store,
    *,
    agent: str,
    language: str,
    max_entries: int = MAX_SLOTS_DEFAULT,
    from_year: int | None = None,
    to_year: int | None = None,
) -> list[LocEntry]:
    """Pull chronicles from the DB and shape them as LocEntry, newest first.

    Why this lives here and not in :class:`Store`:
    the store is event-keyed and chronicle-keyed; this view is *entry-keyed*
    (one row per displayed library slot) and only the loc writer cares about
    that shape. Keeping it in this module avoids polluting Store with a
    Phase-1-specific projection.

    Selection rule: for each event in the year window, pick exactly one
    chronicle row -- the ``(agent, language)`` pair. Events with no matching
    chronicle are skipped silently (they have nothing to render). The result
    is then sorted by year DESC (ties broken by event_id DESC, deterministic
    but unspecified beyond "stable") and truncated to ``max_entries``.
    """
    events = store.list_events(from_year=from_year, to_year=to_year)
    out: list[LocEntry] = []
    for ev in events:
        rows = store.list_chronicles_for_event(ev.event_id, language=language)
        match = next((r for r in rows if r["agent"] == agent), None)
        if match is None:
            continue
        title = (match.get("title") or "").strip()
        body = (match.get("body") or "").strip()
        if not title and not body:
            # Pure empty chronicle (DryRun edge case): skip rather than burn
            # a slot on whitespace.
            continue
        out.append(LocEntry(year=ev.year, title=title, body=body))
    # list_events returns ASC; flip to DESC and truncate.
    out.sort(key=lambda e: e.year, reverse=True)
    return out[:max_entries]
