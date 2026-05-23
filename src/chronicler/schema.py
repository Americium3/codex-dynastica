"""Pydantic models mirroring schemas/event.schema.json.

The JSON Schema is the source of truth; these models exist for ergonomic
construction and validation inside Python code. Keep them in sync.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Source(str, Enum):
    SAVE_IMPORT = "save_import"
    LIVE_HOOK = "live_hook"


class EventType(str, Enum):
    WAR_END = "war_end"
    RULER_DEATH = "ruler_death"
    CORONATION = "coronation"
    MURDER = "murder"
    MARRIAGE = "marriage"
    BIRTH = "birth"
    TITLE_CREATION = "title_creation"
    TITLE_DESTRUCTION = "title_destruction"
    RELIGION_CHANGE = "religion_change"
    HERESY_OUTBREAK = "heresy_outbreak"
    GREAT_HOLY_WAR = "great_holy_war"
    SCHEME_SUCCESS = "scheme_success"
    SCHEME_FAILURE = "scheme_failure"
    SCHEME_ACTIVE = "scheme_active"
    ARTIFACT_ACQUIRED = "artifact_acquired"
    DISASTER = "disaster"
    BATTLE = "battle"
    ACTIVITY = "activity"
    STORY_EVENT = "story_event"


class FactionSide(str, Enum):
    ATTACKER = "attacker"
    DEFENDER = "defender"
    NEUTRAL = "neutral"


class Outcome(str, Enum):
    ATTACKER_VICTORY = "attacker_victory"
    DEFENDER_VICTORY = "defender_victory"
    WHITE_PEACE = "white_peace"
    SUCCESS = "success"
    FAILURE = "failure"
    NATURAL = "natural"
    UNKNOWN = "unknown"


class Location(BaseModel):
    county_id: str | None = None
    county_name: str | None = None
    duchy_name: str | None = None
    kingdom_name: str | None = None
    region: str | None = None


class Actor(BaseModel):
    character_id: str
    name: str
    dynasty: str | None = None
    culture: str | None = None
    religion: str | None = None
    titles: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    age_at_event: int | None = None


class Faction(BaseModel):
    name: str
    side: FactionSide
    religion: str | None = None
    culture: str | None = None


class Casualties(BaseModel):
    attacker_dead: int | None = None
    defender_dead: int | None = None
    civilian_dead_estimate: int | None = None


class ChronicleEvent(BaseModel):
    event_id: str
    source: Source
    type: EventType
    year: int = Field(ge=1, le=4000)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    location: Location | None = None
    primary_actors: list[Actor] = Field(min_length=1)
    secondary_actors: list[Actor] = Field(default_factory=list)
    factions: list[Faction] = Field(default_factory=list)
    religions_involved: list[str] = Field(default_factory=list)
    casualties: Casualties | None = None
    outcome: Outcome | None = None
    tags: list[str] = Field(default_factory=list)
    raw_excerpt: str | None = None
    witnesses: list[str] = Field(default_factory=list)
    # Phase 0.1: a short context block describing the reigning ruler /
    # primary title / dynasty / regnal year. Set once per import; the
    # narrative agents read it on every event so the LLM stops inventing
    # off-screen kings ("King Alaric") out of thin air.
    world_context: str | None = None
    # Phase 0.1.2: per-event note about who held the primary title at
    # ``event.year`` — for events that predate the compiler's reign, this
    # is the only correct anchor for "Nth year of his reign" phrasing.
    # When unset (None), agents should not attempt to cite a regnal year.
    contemporary_ruler: str | None = None
    # Phase 0.3: era_mood describes the ±15-year "weather" around this
    # event — turbulent / ordinary / peaceful — relative to the chronicle's
    # own baseline. Computed by the importer from the density of wars /
    # deaths / disasters in the surrounding window. Drives the peasant
    # ballad's tonal bias: a birth song in a turbulent decade is still
    # joyful but carries a refrain of grief; an ordinary death in a
    # peaceful decade is mourned with extra weight.
    era_mood: str | None = None

    @field_validator("event_id")
    @classmethod
    def _validate_event_id_shape(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 4:
            raise ValueError(
                "event_id must be <source>:<type>:<year>:<hash6>"
            )
        return v


def make_event_id(
    source: Source | str,
    event_type: EventType | str,
    year: int,
    *,
    salt_parts: list[str],
) -> str:
    """Build a stable deterministic event_id.

    salt_parts should contain identifiers that uniquely pin the event
    (e.g. character ids, war id, county id). Order matters — pass them
    in the same order whenever the same logical event is encountered.
    """
    src = source.value if isinstance(source, Source) else source
    et = event_type.value if isinstance(event_type, EventType) else event_type
    salt = "|".join(salt_parts)
    digest = hashlib.sha1(salt.encode("utf-8")).hexdigest()[:6]
    return f"{src}:{et}:{year}:{digest}"
