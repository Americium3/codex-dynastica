"""Generator orchestrator.

Reads events from the store, dispatches each (event, agent, language)
triple to the LLM, and writes results back. Skips triples already
chronicled (idempotent).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .agents import Agent, build_agents  # noqa: F401  (re-exported)
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
    languages: Sequence[str] = ("en",),
    force: bool = False,
) -> GenerationStats:
    """Generate chronicles for the given events × agents × languages.

    `force=True` regenerates even if a chronicle already exists for that
    (event, agent, language) triple.
    """
    stats = GenerationStats()
    for event in events:
        for agent in agents:
            for lang in languages:
                if lang not in agent.supported_languages:
                    log.warning(
                        "Agent %s does not support language %s; skipping",
                        agent.name, lang,
                    )
                    continue
                if not force and store.has_chronicle(event.event_id, agent.name, lang):
                    stats.skipped += 1
                    continue
                try:
                    result = agent.render(event, language=lang)
                except Exception:  # noqa: BLE001 — one bad event must not kill the batch
                    log.exception(
                        "Agent %s failed on %s (lang=%s)",
                        agent.name, event.event_id, lang,
                    )
                    stats.failed += 1
                    continue
                store.save_chronicle(
                    event_id=event.event_id,
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
                stats.generated += 1
                stats.total_cost_usd += result.cost_usd
                stats.total_input_tokens += result.input_tokens
                stats.total_output_tokens += result.output_tokens
                stats.total_cached_tokens += result.cached_input_tokens
                log.info(
                    "Generated %s/%s lang=%s for %s ($%.4f)",
                    agent.name, result.model, lang, event.event_id, result.cost_usd,
                )
    return stats


def generate_range(
    *,
    store: Store,
    agents: list[Agent],
    from_year: int | None = None,
    to_year: int | None = None,
    event_type: EventType | None = None,
    character_id: str | None = None,
    languages: Sequence[str] = ("en",),
    force: bool = False,
) -> GenerationStats:
    events = store.list_events(
        from_year=from_year,
        to_year=to_year,
        event_type=event_type,
        character_id=character_id,
    )
    log.info(
        "Selected %d events for generation in languages: %s",
        len(events), ",".join(languages),
    )
    return generate_for_events(
        store=store,
        agents=agents,
        events=events,
        languages=languages,
        force=force,
    )
