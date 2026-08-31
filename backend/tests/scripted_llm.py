"""Deterministic stand-in for Gemini, for the test suite.

Not a mock in the "returns a fixed blob" sense: each agent registers a handler
that builds a real, schema-valid response from the prompt it was given, so the
workflow takes the same branches it would against a model. Anything unregistered
raises rather than quietly returning something plausible.

It lives here rather than in `app/` on purpose. The product has no simulated
model — `app/adapters/registry.py` builds a real client or refuses to start —
and a double reachable from `app/` is a door into exactly that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ScriptedLLM:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[str, str | None], BaseModel]] = {}
        self.calls: list[tuple[str, str]] = []
        self.seen_untrusted: list[str] = []

    def register(self, agent: str, handler: Callable[[str, str | None], BaseModel]) -> None:
        self._handlers[agent] = handler

    async def structured(
        self,
        *,
        agent: str,
        instruction: str,
        prompt: str,
        schema: type,
        untrusted: str | None = None,
        fast: bool = False,
        mission_id: str = "",
    ) -> Any:
        self.calls.append((agent, prompt[:120]))
        if untrusted:
            self.seen_untrusted.append(untrusted)
        handler = self._handlers.get(agent)
        if handler is None:
            raise KeyError(
                f"ScriptedLLM has no handler for agent '{agent}'. "
                "Register one rather than letting the workflow silently pass."
            )
        result = handler(prompt, untrusted)
        if not isinstance(result, schema):
            raise TypeError(
                f"handler for '{agent}' returned {type(result).__name__}, "
                f"expected {schema.__name__}"
            )
        return result
