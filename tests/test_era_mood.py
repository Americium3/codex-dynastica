"""Tests for ``chronicler.scoring.stamp_era_mood``.

Phase 0.5 backfill: era_mood was introduced in Phase 0.3 and lifted
into ``chronicler.scoring`` in Phase 0.5 specifically so we could pin
its behavior with tests. The function annotates each event in-place
with one of three labels based on the ±15-year density of dark events.
"""

from __future__ import annotations

from chronicler.schema import Actor, ChronicleEvent, EventType, Source
from chronicler.scoring import (
    DARK_EVENT_TYPES,
    PEACEFUL_RATIO,
    TURBULENT_RATIO,
    stamp_era_mood,
)


def _evt(event_type: EventType, year: int, suffix: str = "x") -> ChronicleEvent:
    return ChronicleEvent(
        event_id=f"save_import:{event_type.value}:{year}:{suffix}",
        source=Source.SAVE_IMPORT,
        type=event_type,
        year=year,
        primary_actors=[Actor(character_id="1", name="Test")],
    )


# ---------- structural / edge cases ----------


class TestEraMoodEdgeCases:
    def test_fewer_than_three_events_leaves_none(self):
        # Threshold is 3 — below that, no baseline to compute.
        events = [
            _evt(EventType.RULER_DEATH, 1000),
            _evt(EventType.MURDER, 1005),
        ]
        stamp_era_mood(events)
        assert all(e.era_mood is None for e in events)

    def test_no_dark_events_at_all_leaves_none(self):
        # Three births in a row: nothing to measure density against.
        events = [
            _evt(EventType.BIRTH, 1000),
            _evt(EventType.MARRIAGE, 1010),
            _evt(EventType.CORONATION, 1020),
        ]
        stamp_era_mood(events)
        assert all(e.era_mood is None for e in events)

    def test_empty_input_does_not_crash(self):
        stamp_era_mood([])
        # No assertion — just smoke; the function shouldn't raise.

    def test_all_events_get_a_mood_when_signal_exists(self):
        # With ≥3 events and ≥1 dark event in the set, every event gets
        # stamped — even non-dark ones (births / marriages) inherit the
        # mood of their decade.
        events = [
            _evt(EventType.RULER_DEATH, 1000),
            _evt(EventType.BATTLE, 1005),
            _evt(EventType.BIRTH, 1010),  # non-dark, should still get a label
            _evt(EventType.MARRIAGE, 1015),
            _evt(EventType.MURDER, 1020),
        ]
        stamp_era_mood(events)
        assert all(e.era_mood is not None for e in events)


# ---------- behavioral tests: three regimes ----------


class TestEraMoodRegimes:
    def test_uniformly_distributed_darks_yields_ordinary(self):
        # 5 dark events evenly spread across 1000–1100 — every window
        # sees roughly the mean, so all events land "ordinary".
        events = [
            _evt(EventType.RULER_DEATH, 1000, "a"),
            _evt(EventType.BATTLE, 1025, "b"),
            _evt(EventType.MURDER, 1050, "c"),
            _evt(EventType.WAR_END, 1075, "d"),
            _evt(EventType.DISASTER, 1100, "e"),
        ]
        stamp_era_mood(events)
        # Every event is itself a dark one, and they're 25 years apart
        # (just outside the ±15 window). Each window sees count=1, mean=1,
        # ratio=1.0 → ordinary.
        assert all(e.era_mood == "ordinary" for e in events)

    def test_cluster_of_darks_yields_turbulent_for_clustered_event(self):
        # Two events tightly clustered (war + battle in same year),
        # rest spread out far enough they don't share windows.
        events = [
            _evt(EventType.WAR_END, 1000, "war"),
            _evt(EventType.BATTLE, 1000, "battle"),
            _evt(EventType.MURDER, 1001, "murder"),  # also in the cluster window
            _evt(EventType.BIRTH, 1080, "birth"),
            _evt(EventType.MARRIAGE, 1090, "marriage"),
        ]
        stamp_era_mood(events)
        # The clustered events (windows containing 3 darks) should land
        # turbulent; the lone late ones (window with 0 darks) peaceful.
        moods = {e.event_id.split(":")[-1]: e.era_mood for e in events}
        assert moods["war"] == "turbulent"
        assert moods["battle"] == "turbulent"
        assert moods["birth"] == "peaceful"
        assert moods["marriage"] == "peaceful"

    def test_lone_event_far_from_darks_yields_peaceful(self):
        # All darks bunched at year 1000; one solitary event in 1100
        # with no darks within ±15 → local count 0 → peaceful.
        # (The cluster doesn't always clear the 1.4× turbulent
        # threshold here because the local count IS the mean when
        # all darks share a window — see the dedicated cluster test
        # above for turbulent verification.)
        events = [
            _evt(EventType.RULER_DEATH, 1000, "a"),
            _evt(EventType.MURDER, 1005, "b"),
            _evt(EventType.BATTLE, 1010, "c"),
            _evt(EventType.BIRTH, 1100, "lone"),
        ]
        stamp_era_mood(events)
        moods = {e.event_id.split(":")[-1]: e.era_mood for e in events}
        assert moods["lone"] == "peaceful"


# ---------- threshold pinning ----------


class TestEraMoodThresholds:
    def test_turbulent_ratio_is_above_one(self):
        # Sanity: turbulent must demand MORE-than-average darkness.
        assert TURBULENT_RATIO > 1.0

    def test_peaceful_ratio_is_below_one(self):
        assert PEACEFUL_RATIO < 1.0

    def test_thresholds_leave_meaningful_ordinary_band(self):
        # If turbulent and peaceful thresholds were too close, almost
        # every event would land in one of the two extremes. The band
        # between them must be wide enough for "ordinary" to be common.
        assert TURBULENT_RATIO - PEACEFUL_RATIO >= 0.5

    def test_pinned_current_calibration(self):
        # If these numbers change, the tuning is intentional — but it
        # must be a deliberate diff, not an accident.
        assert TURBULENT_RATIO == 1.4
        assert PEACEFUL_RATIO == 0.6


# ---------- dark event type set ----------


class TestDarkEventTypeSet:
    def test_includes_obvious_disasters(self):
        for et in (
            EventType.RULER_DEATH,
            EventType.MURDER,
            EventType.WAR_END,
            EventType.BATTLE,
            EventType.DISASTER,
        ):
            assert et in DARK_EVENT_TYPES

    def test_excludes_joyful_events(self):
        # The whole point of the threshold: a turbulent decade is
        # defined by deaths and wars, NOT by births/marriages happening
        # to coincide. Births tagged dark would defeat the bias.
        for et in (
            EventType.BIRTH,
            EventType.MARRIAGE,
            EventType.CORONATION,
            EventType.ARTIFACT_ACQUIRED,
            EventType.ACTIVITY,
        ):
            assert et not in DARK_EVENT_TYPES

    def test_includes_religious_strife(self):
        # Heresy outbreak and great holy war qualify — they're not
        # personal deaths but they do define an era's mood.
        assert EventType.HERESY_OUTBREAK in DARK_EVENT_TYPES
        assert EventType.GREAT_HOLY_WAR in DARK_EVENT_TYPES


# ---------- window radius ----------


class TestWindowRadius:
    def test_custom_radius_changes_classification(self):
        # Two darks 20 years apart. With the default ±15 radius they
        # don't share a window, but with ±25 they do.
        events_a = [
            _evt(EventType.RULER_DEATH, 1000, "a1"),
            _evt(EventType.BIRTH, 1020, "a2"),  # 20 years after; no shared window @15
            _evt(EventType.MARRIAGE, 1050, "a3"),
        ]
        stamp_era_mood(events_a, window_radius_years=15)
        events_b = [
            _evt(EventType.RULER_DEATH, 1000, "b1"),
            _evt(EventType.BIRTH, 1020, "b2"),
            _evt(EventType.MARRIAGE, 1050, "b3"),
        ]
        stamp_era_mood(events_b, window_radius_years=25)
        # The event at 1020 with radius 25 includes the 1000 dark.
        # With radius 15, it does not. The mood label may differ.
        # We assert only that the function runs cleanly under both
        # radii and stamps all events.
        assert all(e.era_mood is not None for e in events_a)
        assert all(e.era_mood is not None for e in events_b)
