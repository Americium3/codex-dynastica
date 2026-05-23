"""Narrative agents: each agent renders events from a distinct voice/perspective."""

from .base import Agent, AgentResult, ClaudeClient, DryRunClient, LLMClient
from .court_historian import CourtHistorian
from .peasant_ballad import PeasantBallad

ALL_AGENTS: list[type[Agent]] = [CourtHistorian, PeasantBallad]


def build_agents(client: LLMClient) -> list[Agent]:
    """Instantiate every registered agent against a shared LLM client."""
    return [cls(client) for cls in ALL_AGENTS]


__all__ = [
    "Agent",
    "AgentResult",
    "ALL_AGENTS",
    "ClaudeClient",
    "CourtHistorian",
    "DryRunClient",
    "LLMClient",
    "PeasantBallad",
    "build_agents",
]
