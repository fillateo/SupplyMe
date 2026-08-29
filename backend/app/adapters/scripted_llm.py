"""Deterministic stand-in for Gemini.

Used by the test suite and by offline demo runs. It is not a mock of an LLM in
the "returns a fixed blob" sense — each agent registers a handler that builds a
real, schema-valid response from the prompt, so the workflow exercises the same
branches. Anything unregistered raises rather than returning something plausible.
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
