"""Significance scoring + scope presets — shared between the save-file
importer (``scripts/import_dynasty.py``) and the live-hook watcher
(``parsers/live_hook.py`` via the ``watch`` CLI command).

Phase 0.3 introduced the significance table inside the importer. Phase
0.4 lifts it into the package so the same ranking can gate which
live-hook events are passed to the LLM in real time — saves a token
budget on flavor events without dropping them from the database.

Scope presets (Phase 0.4) make ``--scope`` carry both *what* to pull
AND *how strict* the cutoff is, so the player picks one knob instead of
three. ``dynastic`` and ``middle`` share the medium preset (the Phase
0.3 calibration); ``narrow`` tightens; ``wide`` loosens.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import ChronicleEvent, EventType


# Higher = more newsworthy. The chronicle keeps the top-N by this score,
# tie-broken by recency. Calibrated so an ordinary house-member death
# loses to a battle the holder commanded, but a holder's own death beats
# almost anything else.
SIGNIFICANCE: dict[EventType, int] = {
    EventType.MURDER:             100,
    EventType.RULER_DEATH:         95,
    EventType.WAR_END:             92,
    EventType.GREAT_HOLY_WAR:      92,
    EventType.CORONATION:          88,
    EventType.BATTLE:              82,
    EventType.HERESY_OUTBREAK:     78,
    EventType.RELIGION_CHANGE:     74,
    EventType.TITLE_CREATION:      70,
    EventType.TITLE_DESTRUCTION:   70,
    EventType.BIRTH:               64,   # heir; ordinary house births score lower via tag bump
    EventType.MARRIAGE:            60,
    EventType.ARTIFACT_ACQUIRED:   55,
    EventType.DISASTER:            52,
    EventType.SCHEME_SUCCESS:      50,
    EventType.SCHEME_FAILURE:      50,
    EventType.SCHEME_ACTIVE:       42,
    EventType.ACTIVITY:            38,
    EventType.STORY_EVENT:         34,
}


def significance(e: ChronicleEvent) -> int:
    """Score an event for selection ranking.

    Base score comes from the type table. We then nudge it based on tags:
      * ``heir`` tag → +12 (heir births/deaths beat ordinary house events)
      * ``title:`` tag (primary title) → +6 (spine events beat foreign events)
      * ``notable_ruler`` tag (wide-scope foreign death) → −15
      * ``house_member`` tag without ``heir`` → −8 (great-aunt's death is a footnote)
      * artifact ``rarity:famed`` / ``rarity:illustrious`` → +10
    """
    base = SIGNIFICANCE.get(e.type, 30)
    tags = set(e.tags or [])
    if "heir" in tags:
        base += 12
    if any(t.startswith("title:") for t in tags):
        base += 6
    if "notable_ruler" in tags:
        base -= 15
    if "house_member" in tags and "heir" not in tags:
        base -= 8
    if "rarity:famed" in tags or "rarity:illustrious" in tags:
        base += 10
    return base


@dataclass(frozen=True)
class ScopePreset:
    """Strictness profile that ships with each ``--scope`` choice.

    Attributes
    ----------
    max_per_type
        Per-EventType cap before the global cut. None on ``wide`` to let
        any single category fill the chronicle if the world really is
        that lopsided in this window.
    max_events
        Global cap. None means no batch-mode cap (real-time mode never
        needs one because events arrive incrementally).
    min_live_significance
        Minimum ``significance()`` score for an incoming live-hook
        event to actually be sent to the LLM. Events that score below
        still hit the database — they are *kept*, just not *narrated*.
        Set to 0 to narrate everything that comes in.
    """

    max_per_type: int | None
    max_events: int | None
    min_live_significance: int


# Phase 0.4 scope presets. ``dynastic`` is kept as an alias of ``middle``
# so the Phase 0.1 default still resolves cleanly. ``narrow`` and
# ``wide`` are recalibrated per the user's Phase 0.4 spec: medium = the
# Phase 0.3 numbers (max_per_type=3, max_events=12).
SCOPE_PRESETS: dict[str, ScopePreset] = {
    "narrow":   ScopePreset(max_per_type=2, max_events=6,  min_live_significance=70),
    "dynastic": ScopePreset(max_per_type=3, max_events=12, min_live_significance=55),
    "middle":   ScopePreset(max_per_type=3, max_events=12, min_live_significance=55),
    "wide":     ScopePreset(max_per_type=5, max_events=24, min_live_significance=40),
}


def resolve_scope(name: str) -> ScopePreset:
    """Resolve a ``--scope`` string to its preset. Unknown names fall
    back to ``middle`` rather than raising; callers should validate the
    argparse choice list separately."""
    return SCOPE_PRESETS.get(name, SCOPE_PRESETS["middle"])
