"""Narrative agents: each agent renders events from a distinct voice/perspective."""

from .base import Agent, AgentResult, ClaudeClient, DryRunClient, LLMClient, OllamaClient
from .court_historian import CourtHistorian
from .peasant_ballad import PeasantBallad

ALL_AGENTS: list[type[Agent]] = [CourtHistorian, PeasantBallad]
AGENTS_BY_NAME: dict[str, type[Agent]] = {cls.name: cls for cls in ALL_AGENTS}


def build_agents(
    client: LLMClient,
    *,
    model_override: str | None = None,
    only: list[str] | None = None,
) -> list[Agent]:
    """Instantiate registered agents against a shared LLM client.

    ``model_override`` is forwarded to each Agent (used by local-model
    backends so every event routes to the same model). ``only`` filters
    the agent set to the named subset, e.g. ``["court_historian"]``.
    """
    if only:
        unknown = [n for n in only if n not in AGENTS_BY_NAME]
        if unknown:
            raise ValueError(
                f"Unknown agent(s): {unknown}. Known: {sorted(AGENTS_BY_NAME)}"
            )
        classes = [AGENTS_BY_NAME[n] for n in only]
    else:
        classes = ALL_AGENTS
    return [cls(client, model_override=model_override) for cls in classes]


__all__ = [
    "Agent",
    "AgentResult",
    "AGENTS_BY_NAME",
    "ALL_AGENTS",
    "ClaudeClient",
    "CourtHistorian",
    "DryRunClient",
    "LLMClient",
    "OllamaClient",
    "PeasantBallad",
    "build_agents",
]
