"""Providers that refuse to be called.

What `SUPPLYME_MOCK=true` binds in place of Gemini, search, Places and the
mailbox. They return nothing and invent nothing: every method raises.

That is the point. The alternative — a provider that answers with plausible
fixture data — is the thing this codebase removed in "There is no simulated
mode", because it produced a system whose most convincing demonstration was of
suppliers that do not exist. A replay of a mission that really ran is a
different claim from a simulation of one, and it stays a different claim only
if nothing in the process can quietly manufacture a supplier when the recording
runs out. So if any code path reaches a provider during a replay, it fails
loudly and names itself, instead of filling the gap.
"""

from __future__ import annotations

from typing import Any, NoReturn


class InertProvider:
    """Raises on any attribute access that is then called."""

    def __init__(self, what: str) -> None:
        self._what = what

    def __getattr__(self, name: str) -> Any:
        def _refuse(*_args: Any, **_kwargs: Any) -> NoReturn:
            raise RuntimeError(
                f"SUPPLYME_MOCK is on, so no {self._what} is bound, and "
                f"{self._what}.{name}() was called anyway. Mock mode replays a "
                "recorded mission and must never reach a provider: this is a bug "
                "in the replay, not a reason to invent an answer."
            )

        return _refuse

    def __repr__(self) -> str:  # what /api/health reports
        return f"Inert{self._what.title().replace(' ', '')}"
