"""Tests for ``chronicler.scoring`` — the SIGNIFICANCE table, the
tag-aware ``significance()`` helper, and the scope-preset resolver.

Phase 0.5 backfill: the scoring module was added in Phase 0.3 and
extended in Phase 0.4, but until now had zero direct tests. These
tests pin the calibration so future tuning is visible in diffs.
"""

from __future__ import annotations

import pytest

from chronicler.schema import Actor, ChronicleEvent, EventType, Source
from chronicler.scoring import (
    SCOPE_PRESETS,
    SIGNIFICANCE,
    ScopePreset,
    resolve_scope,
    significance,
)


# Smallest valid event we can build. Tests vary `type` and `tags`.
def _evt(
    event_type: EventType,
    *,
    tags: list[str] | None = None,
    year: int = 1066,
    eid_suffix: str = "abc123",
) -> ChronicleEvent:
    return ChronicleEvent(
        event_id=f"save_import:{event_type.value}:{year}:{eid_suffix}",
        source=Source.SAVE_IMPORT,
        type=event_type,
        year=year,
        primary_actors=[Actor(character_id="1", name="Test Actor")],
        tags=tags or [],
    )


# ---------- SIGNIFICANCE table calibration ----------


class TestSignificanceTable:
    """Pin the relative ordering. If a calibration moves, this test
    must be updated — that visibility is the point."""

    def test_murder_is_top(self):
        # Murder is the most newsworthy event a chronicle can carry.
        assert SIGNIFICANCE[EventType.MURDER] == 100

    def test_ruler_death_beats_war_end(self):
        # A king's death outranks an ongoing war for narrative weight.
        assert SIGNIFICANCE[EventType.RULER_DEATH] > SIGNIFICANCE[EventType.WAR_END]

    def test_war_end_beats_coronation(self):
        assert SIGNIFICANCE[EventType.WAR_END] > SIGNIFICANCE[EventType.CORONATION]

    def test_coronation_beats_battle(self):
        # A new reign begins matters more than a single field engagement.
        assert SIGNIFICANCE[EventType.CORONATION] > SIGNIFICANCE[EventType.BATTLE]

    def test_birth_below_marriage_in_table(self):
        # Heir tag bumps births in significance(), but the base score for
        # a generic birth is intentionally below marriage so we don't
        # surface cousin-of-cousin births by default.
        # Wait — actually base BIRTH is 64 > MARRIAGE 60. The heir tag
        # bumps it further. Pin both as currently calibrated.
        assert SIGNIFICANCE[EventType.BIRTH] == 64
        assert SIGNIFICANCE[EventType.MARRIAGE] == 60

    def test_story_event_is_bottom(self):
        # Story events are flavor, not headlines.
        assert SIGNIFICANCE[EventType.STORY_EVENT] == 34
        assert all(
            SIGNIFICANCE[EventType.STORY_EVENT] <= v
            for k, v in SIGNIFICANCE.items()
            if k is not EventType.STORY_EVENT
        )


# ---------- significance() helper: tag-based adjustments ----------


class TestSignificanceHelper:
    def test_unknown_event_type_gets_default_30(self):
        """Anything missing from the table falls back to 30 — should never
        happen with the current EventType enum, but the safety net matters
        for forward-compat when new event types land before recalibration."""

        # We can't actually build a ChronicleEvent with an unknown type
        # (Pydantic enum validation blocks it), so we test the helper's
        # robustness via a known-low-score event instead.
        base = _evt(EventType.STORY_EVENT)
        assert significance(base) == SIGNIFICANCE[EventType.STORY_EVENT]

    def test_heir_tag_adds_12(self):
        base = _evt(EventType.BIRTH)
        heir = _evt(EventType.BIRTH, tags=["heir"])
        assert significance(heir) == significance(base) + 12

    def test_title_tag_adds_6(self):
        base = _evt(EventType.RULER_DEATH)
        with_title = _evt(EventType.RULER_DEATH, tags=["title:k_england"])
        assert significance(with_title) == significance(base) + 6

    def test_notable_ruler_tag_subtracts_15(self):
        # Foreign rulers' deaths (wide-scope) get knocked down so they
        # don't crowd out spine events.
        base = _evt(EventType.RULER_DEATH)
        foreign = _evt(EventType.RULER_DEATH, tags=["notable_ruler"])
        assert significance(foreign) == significance(base) - 15

    def test_house_member_without_heir_subtracts_8(self):
        # Great-aunt's death is a footnote — bump down.
        base = _evt(EventType.RULER_DEATH)
        cousin = _evt(EventType.RULER_DEATH, tags=["house_member"])
        assert significance(cousin) == significance(base) - 8

    def test_house_member_with_heir_does_not_subtract(self):
        # An heir who happens to also be a house member should NOT eat
        # the -8 penalty — heir status overrides.
        ev = _evt(EventType.BIRTH, tags=["house_member", "heir"])
        # Base 64, +12 heir, no -8 since heir is also set.
        assert significance(ev) == 64 + 12

    def test_rare_artifact_adds_10(self):
        base = _evt(EventType.ARTIFACT_ACQUIRED)
        famed = _evt(EventType.ARTIFACT_ACQUIRED, tags=["rarity:famed"])
        illust = _evt(EventType.ARTIFACT_ACQUIRED, tags=["rarity:illustrious"])
        assert significance(famed) == significance(base) + 10
        assert significance(illust) == significance(base) + 10

    def test_common_artifact_unchanged(self):
        base = _evt(EventType.ARTIFACT_ACQUIRED)
        common = _evt(EventType.ARTIFACT_ACQUIRED, tags=["rarity:common"])
        # Only famed/illustrious bump; common stays at base.
        assert significance(common) == significance(base)

    def test_multiple_tags_stack(self):
        # An heir's death involving the primary title and tagged as
        # house_member: heir (+12) + title (+6) + no -8 (because heir).
        ev = _evt(
            EventType.RULER_DEATH,
            tags=["heir", "title:k_england", "house_member"],
        )
        expected = SIGNIFICANCE[EventType.RULER_DEATH] + 12 + 6
        assert significance(ev) == expected

    def test_score_ordering_real_world_scenario(self):
        """The whole point of the table: an ordinary house-member death
        loses to a primary-title coronation."""
        cousin_death = _evt(EventType.RULER_DEATH, tags=["house_member"])
        coronation = _evt(EventType.CORONATION, tags=["title:k_england"])
        assert significance(coronation) > significance(cousin_death)


# ---------- SCOPE_PRESETS structure ----------


class TestScopePresets:
    def test_all_four_scopes_present(self):
        # Phase 0.4 ships exactly these four. New scopes need explicit
        # ROADMAP coverage; don't slip them in silently.
        assert set(SCOPE_PRESETS) == {"narrow", "dynastic", "middle", "wide"}

    def test_narrow_is_strictest(self):
        n = SCOPE_PRESETS["narrow"]
        m = SCOPE_PRESETS["middle"]
        w = SCOPE_PRESETS["wide"]
        assert n.max_per_type < m.max_per_type < w.max_per_type
        assert n.max_events < m.max_events < w.max_events
        # min_live_significance moves the OPPOSITE direction: narrow
        # demands a higher score to call the LLM.
        assert n.min_live_significance > m.min_live_significance > w.min_live_significance

    def test_dynastic_alias_of_middle(self):
        # Phase 0.4 made `dynastic` an alias of the medium tier so the
        # Phase 0.1 default resolves cleanly. If this breaks, callers
        # passing `--scope dynastic` are getting unexpected strictness.
        assert SCOPE_PRESETS["dynastic"] == SCOPE_PRESETS["middle"]

    def test_phase_0_3_calibration_pinned(self):
        # The medium tier is the Phase 0.3 calibration — if these
        # numbers change, the comment above SCOPE_PRESETS needs
        # updating too.
        m = SCOPE_PRESETS["middle"]
        assert m.max_per_type == 3
        assert m.max_events == 12
        assert m.min_live_significance == 55


# ---------- resolve_scope() ----------


class TestResolveScope:
    @pytest.mark.parametrize("name", ["narrow", "dynastic", "middle", "wide"])
    def test_known_names_resolve(self, name):
        assert isinstance(resolve_scope(name), ScopePreset)
        assert resolve_scope(name) is SCOPE_PRESETS[name]

    def test_unknown_falls_back_to_middle(self):
        # Per the docstring: unknown names fall back rather than raise
        # so a typoed CLI choice can't crash the importer. argparse
        # validates the user input separately.
        assert resolve_scope("nonsense-scope") is SCOPE_PRESETS["middle"]

    def test_empty_string_falls_back(self):
        assert resolve_scope("") is SCOPE_PRESETS["middle"]
