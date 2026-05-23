"""Generator orchestrator.

Reads events from the store, dispatches each (event, agent) pair to the
LLM, and writes results back. Skips pairs already chronicled (idempotent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from .agents import Agent, build_agents  # noqa: F401  (re-exported for convenience)
from .schema import ChronicleEvent, EventType
from .storage import Store

log = logging.getLogger(__name__)


@dataclass
class GenerationStats:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0


def generate_for_events(
    *,
    store: Store,
    agents: list[Agent],
    events: Iterable[ChronicleEvent],
    force: bool = False,
) -> GenerationStats:
    """Generate chronicles for the given events.

    `force=True` regenerates even if a chronicle already exists for that
    (event, agent) pair.
    """
    stats = GenerationStats()
    for event in events:
        for agent in agents:
            if not force and store.has_chronicle(event.event_id, agent.name):
                stats.skipped += 1
                continue
            try:
                result = agent.render(event)
            except Exception:  # noqa: BLE001 — we want one bad event not to kill the batch
                log.exception("Agent %s failed on %s", agent.name, event.event_id)
                stats.failed += 1
                continue
            store.save_chronicle(
                event_id=event.event_id,
                agent=agent.name,
                title=result.title,
                body=result.body,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_input_tokens=result.cached_input_tokens,
                cost_usd=result.cost_usd,
            )
            stats.generated += 1
            stats.total_cost_usd += result.cost_usd
            stats.total_input_tokens += result.input_tokens
            stats.total_output_tokens += result.output_tokens
            stats.total_cached_tokens += result.cached_input_tokens
            log.info(
                "Generated %s/%s for %s (%s, $%.4f)",
                agent.name,
                result.model,
                event.event_id,
                f"in={result.input_tokens}/out={result.output_tokens}/cache={result.cached_input_tokens}",
                result.cost_usd,
            )
    return stats


def generate_range(
    *,
    store: Store,
    agents: list[Agent],
    from_year: Optional[int] = None,
    to_year: Optional[int] = None,
    event_type: Optional[EventType] = None,
    character_id: Optional[str] = None,
    force: bool = False,
) -> GenerationStats:
    events = store.list_events(
        from_year=from_year,
        to_year=to_year,
        event_type=event_type,
        character_id=character_id,
    )
    log.info("Selected %d events for generation", len(events))
    return generate_for_events(
        store=store, agents=agents, events=events, force=force
    )
