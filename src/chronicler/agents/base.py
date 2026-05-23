"""Agent base class + LLM client (real Claude + dry-run mock).

Prompt caching strategy
-----------------------
Each agent has a long, static system prompt (its persona/voice). We mark
that block with `cache_control: ephemeral` so subsequent calls within the
5-minute TTL hit the cache. The per-event payload is small and goes in
the user message — not cached.

Cost tracking
-------------
We pass back input_tokens / output_tokens / cache_read_input_tokens /
cache_creation_input_tokens and compute a $ estimate against a static
price table. Update PRICING when Anthropic publishes new rates.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Protocol
from urllib import request as _urlrequest
from urllib.error import URLError

from ..schema import ChronicleEvent

log = logging.getLogger(__name__)


# USD per million tokens. Adjust to current Anthropic pricing.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7":          {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-6":        {"input":  3.00, "output": 15.00, "cache_read": 0.30, "cache_write":  3.75},
    "claude-haiku-4-5-20251001":{"input":  1.00, "output":  5.00, "cache_read": 0.10, "cache_write":  1.25},
}

DEFAULT_MAJOR_MODEL = "claude-opus-4-7"
DEFAULT_MINOR_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class AgentResult:
    title: str
    body: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: float


class LLMClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: list[dict],
        messages: list[dict],
        max_tokens: int,
    ) -> dict:
        """Returns a dict with keys: text, input_tokens, output_tokens,
        cache_read_input_tokens, cache_creation_input_tokens."""
        ...


class ClaudeClient:
    """Real Anthropic SDK client. Imported lazily so the package works
    without anthropic installed (tests use DryRunClient)."""

    def __init__(self, api_key: Optional[str] = None):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from e
        self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def complete(self, *, model, system, messages, max_tokens):
        resp = self._client.messages.create(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        u = resp.usage
        return {
            "text": text,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }


class OllamaClient:
    """Local-model client targeting an Ollama server (default :11434).

    Why this exists
    ---------------
    Phase 0 originally assumed Claude. Users without an Anthropic key can
    point this client at a local model (e.g. ``gemma3:27b``) and get a
    chronicle entirely on-device. The Agent layer passes a Claude-style
    model name in via ``model=``; this client ignores it and uses its own
    ``default_model``, because the Anthropic/Ollama model namespaces don't
    overlap.

    Prompt-cache fields
    -------------------
    Ollama has no equivalent of Anthropic's ``cache_control``. We strip
    those blocks before sending. Cache token counts are reported as 0.

    Token accounting
    ----------------
    Ollama reports ``prompt_eval_count`` / ``eval_count`` in /api/chat
    responses. We surface those as input/output tokens. ``estimate_cost``
    returns 0 for unknown models, so local-model runs show $0 spend —
    that is correct.
    """

    def __init__(
        self,
        *,
        model: str = "gemma3:27b",
        base_url: str = "http://localhost:11434",
        timeout: float = 600.0,
        temperature: float = 0.8,
    ):
        self.default_model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature

    def _flatten(self, blocks: list[dict] | str) -> str:
        if isinstance(blocks, str):
            return blocks
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)

    def complete(self, *, model, system, messages, max_tokens):
        # Ignore the incoming Anthropic-style model name; use ours.
        target_model = self.default_model
        ollama_messages = [{"role": "system", "content": self._flatten(system)}]
        for m in messages:
            ollama_messages.append({"role": m["role"], "content": self._flatten(m["content"])})
        payload = {
            "model": target_model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = _urlrequest.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _urlrequest.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            raise RuntimeError(
                f"Ollama request to {self.base_url} failed: {e}. "
                f"Is `ollama serve` running and is the model '{target_model}' pulled?"
            ) from e
        text = (body.get("message") or {}).get("content", "")
        return {
            "text": text,
            "input_tokens": int(body.get("prompt_eval_count") or 0),
            "output_tokens": int(body.get("eval_count") or 0),
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }


class DryRunClient:
    """Mock LLM: returns deterministic stub text. Useful for offline tests
    and for verifying the full pipeline without spending API credit."""

    def __init__(self, prefix: str = "[DRY-RUN]"):
        self.prefix = prefix
        self.calls: list[dict] = []

    def complete(self, *, model, system, messages, max_tokens):
        self.calls.append(
            {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens}
        )
        # Echo the last user message back with a marker so the surrounding
        # pipeline can be verified end-to-end.
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        if isinstance(last_user, list):
            last_user = " ".join(
                blk.get("text", "") for blk in last_user if isinstance(blk, dict)
            )
        excerpt = last_user[:120].replace("\n", " ")
        return {
            "text": f"{self.prefix} {excerpt}…",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    price = PRICING.get(model)
    if not price:
        return 0.0
    fresh_input = max(0, input_tokens - cache_read_input_tokens - cache_creation_input_tokens)
    return (
        fresh_input * price["input"]
        + output_tokens * price["output"]
        + cache_read_input_tokens * price["cache_read"]
        + cache_creation_input_tokens * price["cache_write"]
    ) / 1_000_000


class Agent(ABC):
    """Base class for a narrative agent.

    Subclasses provide:
    - name: stable id stored in DB
    - display_name: shown in UI
    - system_prompt(language): the cached persona block, per output language
    - user_prompt(event, language): the per-event input, per output language
    - model_for(event): which Claude model to use

    The language is part of the agent's render call signature so the same
    Agent instance can produce both English and Chinese chronicles in one
    run without re-instantiation.
    """

    name: str = "agent"
    display_name: str = "Agent"
    supported_languages: tuple[str, ...] = ("en", "zh")

    def __init__(
        self,
        client: LLMClient,
        *,
        max_tokens: int = 350,
        model_override: Optional[str] = None,
    ):
        self.client = client
        self.max_tokens = max_tokens
        # When set, bypasses `model_for()`. Used by the Ollama backend so
        # every event routes to e.g. gemma3:27b regardless of severity tier.
        self.model_override = model_override

    @abstractmethod
    def system_prompt(self, language: str = "en") -> str: ...

    @abstractmethod
    def user_prompt(self, event: ChronicleEvent, language: str = "en") -> str: ...

    def model_for(self, event: ChronicleEvent) -> str:
        if self.model_override:
            return self.model_override
        major = {"war_end", "great_holy_war", "coronation", "ruler_death", "murder"}
        return DEFAULT_MAJOR_MODEL if event.type.value in major else DEFAULT_MINOR_MODEL

    def render(self, event: ChronicleEvent, language: str = "en") -> AgentResult:
        if language not in self.supported_languages:
            raise ValueError(
                f"Agent {self.name} does not support language {language!r}. "
                f"Supported: {self.supported_languages}"
            )
        system = [
            {
                "type": "text",
                "text": self.system_prompt(language),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        messages = [
            {
                "role": "user",
                "content": self.user_prompt(event, language),
            }
        ]
        model = self.model_for(event)
        log.debug(
            "Agent %s rendering %s lang=%s with %s",
            self.name, event.event_id, language, model,
        )
        resp = self.client.complete(
            model=model,
            system=system,
            messages=messages,
            max_tokens=self.max_tokens,
        )
        text = resp["text"].strip()
        title, body = _split_title_body(text)
        cost = estimate_cost(
            model,
            input_tokens=resp["input_tokens"],
            output_tokens=resp["output_tokens"],
            cache_read_input_tokens=resp["cache_read_input_tokens"],
            cache_creation_input_tokens=resp["cache_creation_input_tokens"],
        )
        return AgentResult(
            title=title,
            body=body,
            model=model,
            input_tokens=resp["input_tokens"],
            output_tokens=resp["output_tokens"],
            cached_input_tokens=resp["cache_read_input_tokens"],
            cache_creation_input_tokens=resp["cache_creation_input_tokens"],
            cost_usd=cost,
        )


def _split_title_body(text: str) -> tuple[str, str]:
    """Conventions: agent returns first line as title (optionally prefixed
    with ``# ``), then a blank line, then body. Falls back gracefully if not.

    Also strips lingering Markdown separators (``---``) that local models
    sometimes emit between title and body.
    """
    lines = text.strip().split("\n")
    if not lines:
        return ("Untitled", "")
    first = lines[0].lstrip("# *").strip().strip("*")
    rest = lines[1:] if len(lines) > 1 else []
    # Drop leading blank lines + lingering separators ("---", "***", "===").
    while rest and (rest[0].strip() == "" or set(rest[0].strip()) <= {"-", "*", "=", "—", "–", "_"}):
        rest = rest[1:]
    if rest:
        return (first, "\n".join(rest).strip())
    if len(first) <= 80 and len(lines) > 1:
        return (first, "\n".join(lines[1:]).strip())
    return ("Untitled", text.strip())


def event_brief(event: ChronicleEvent) -> str:
    """Compact JSON-ish brief of an event for prompt injection.

    If the event carries ``world_context`` (set by the dynastic-scope
    importer), it is rendered first — this anchors the narrator to the
    real reigning ruler / primary title / dynasty so the model doesn't
    fabricate a "King Alaric" out of thin air.
    """
    primary = ", ".join(
        f"{a.name} ({a.dynasty or '—'}, {a.culture or '—'}, {a.religion or '—'}, traits={','.join(a.traits[:4]) or '—'})"
        for a in event.primary_actors
    )
    factions = "; ".join(f"{f.side.value}: {f.name}" for f in event.factions) or "—"
    loc = event.location
    loc_str = "—"
    if loc:
        parts = [loc.county_name, loc.duchy_name, loc.kingdom_name, loc.region]
        loc_str = ", ".join([p for p in parts if p]) or "—"
    cas = event.casualties
    cas_str = (
        f"attacker_dead={cas.attacker_dead}, defender_dead={cas.defender_dead}"
        if cas else "—"
    )
    ctx_block = ""
    if event.world_context:
        ctx_block = f"WORLD CONTEXT (the chronicle's present compiler):\n{event.world_context.strip()}\n\n"
    # An eye-catching banner around the event date — local models otherwise
    # tend to anchor every entry to the WORLD CONTEXT compilation date.
    date_str = f"{event.year} AD"
    if event.month and event.day:
        date_str = f"{event.year}-{event.month:02d}-{event.day:02d} AD"
    contemp = (
        f"contemporary_ruler={event.contemporary_ruler}\n"
        if event.contemporary_ruler else ""
    )
    # Phase 0.3: era_mood tells downstream agents (esp. the peasant
    # ballad) how turbulent the surrounding decade is. The ballad uses
    # this to bias tone — a birth song in a turbulent era still rejoices
    # but carries an undercurrent of grief.
    mood = f"era_mood={event.era_mood}\n" if event.era_mood else ""
    return (
        f"{ctx_block}"
        f"=== EVENT TO CHRONICLE (entry MUST be set in this event's year, NOT the compilation year) ===\n"
        f"date={date_str}\n"
        f"{contemp}"
        f"{mood}"
        f"type={event.type.value}\n"
        f"location={loc_str}\n"
        f"primary_actors={primary}\n"
        f"factions={factions}\n"
        f"outcome={event.outcome.value if event.outcome else '—'}\n"
        f"casualties={cas_str}\n"
        f"tags={', '.join(event.tags) or '—'}\n"
    )
