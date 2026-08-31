"""What a mission costs, measured rather than assumed.

Token counts come from the API's own `usage_metadata`, so the numbers here are
what was actually billed for, not an estimate of what should have been. The
prices are the one part that has to be configured — they change, and a stale
table silently under-reports — so they are declared in one place, stamped with
when they were last checked, and overridable.

The budget is a real stop, not a warning. A mission that reaches its cap fails
with a reason rather than continuing to spend, because the failure mode this
guards against is a loop nobody is watching at 3am.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

#: USD per million tokens. Verify against current Vertex AI pricing before
#: relying on the totals — these were entered on 2026-08-30 and Google changes
#: them. Committed volume or a regional rate would make these wrong; edit the
#: table rather than looking for a setting, because there is not one.
PRICING: dict[str, tuple[float, float]] = {
    # model prefix     (input $/1M, output $/1M)
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3-flash": (0.30, 2.50),
    "gemini-3-pro": (2.00, 12.00),
    "gemini-3.5-flash": (0.40, 3.00),
    "gemini-3.5-pro": (2.50, 15.00),
}
#: Used when a model is not in the table. Deliberately the most expensive rate
#: on the list: an unknown model should over-report, never under-report, or the
#: budget stops protecting anything.
UNKNOWN_PRICE = (2.50, 15.00)


def price_for(model: str) -> tuple[float, float]:
    """Longest-prefix match, so `gemini-2.5-flash-002` prices as 2.5-flash."""
    best: tuple[float, float] | None = None
    best_length = -1
    for prefix, price in PRICING.items():
        if model.startswith(prefix) and len(prefix) > best_length:
            best, best_length = price, len(prefix)
    return best if best is not None else UNKNOWN_PRICE


def usd_for(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = price_for(model)
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usd": round(self.usd, 6),
        }


class BudgetExceeded(RuntimeError):
    """A mission hit its model-call or spend cap. Not retryable."""


@dataclass
class CostMeter:
    """Per-mission model usage, plus the caps that stop a runaway.

    Held in memory per process. It is a spend guard, not an accounting ledger —
    the authoritative number is the one on your Cloud Billing page, and the
    totals are also written onto the mission so they survive a restart.
    """

    #: Overridden by Settings wherever this is built for real; these are here
    #: only so a direct construction is bounded, and they track config.py.
    max_calls_per_mission: int = 300
    max_usd_per_mission: float = 1.00
    _by_mission: dict[str, Usage] = field(default_factory=dict)
    _total: Usage = field(default_factory=Usage)
    _lock: Lock = field(default_factory=Lock)

    def record(
        self, mission_id: str, model: str, input_tokens: int, output_tokens: int
    ) -> Usage:
        cost = usd_for(model, input_tokens, output_tokens)
        with self._lock:
            usage = self._by_mission.setdefault(mission_id or "unattributed", Usage())
            usage.calls += 1
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.usd += cost
            self._total.calls += 1
            self._total.input_tokens += input_tokens
            self._total.output_tokens += output_tokens
            self._total.usd += cost
            return Usage(usage.calls, usage.input_tokens, usage.output_tokens, usage.usd)

    def usage(self, mission_id: str) -> Usage:
        with self._lock:
            found = self._by_mission.get(mission_id)
            if found is None:
                return Usage()
            return Usage(found.calls, found.input_tokens, found.output_tokens, found.usd)

    @property
    def total(self) -> Usage:
        with self._lock:
            return Usage(
                self._total.calls, self._total.input_tokens,
                self._total.output_tokens, self._total.usd,
            )

    def check(self, mission_id: str) -> None:
        """Raise before spending more on a mission that has had its share."""
        if not mission_id:
            return
        usage = self.usage(mission_id)
        if usage.calls >= self.max_calls_per_mission:
            raise BudgetExceeded(
                f"mission reached its {self.max_calls_per_mission}-model-call cap "
                f"(spent about ${usage.usd:.3f}). Raise SUPPLYME_MAX_MODEL_CALLS_PER_MISSION "
                "if this mission genuinely needs more."
            )
        if usage.usd >= self.max_usd_per_mission:
            raise BudgetExceeded(
                f"mission reached its ${self.max_usd_per_mission:.2f} cap after "
                f"{usage.calls} model calls. Raise SUPPLYME_MAX_USD_PER_MISSION to allow more."
            )

    def seed(self, mission_id: str, usage: Usage) -> None:
        """Restore a mission's totals after a process restart.

        Copied, not adopted. `record` mutates the stored Usage in place, so
        keeping the caller's object would make their copy climb with the meter —
        and a caller holding it as a "what I have already written" marker would
        then never see a difference to write.
        """
        with self._lock:
            self._by_mission[mission_id] = Usage(
                usage.calls, usage.input_tokens, usage.output_tokens, usage.usd
            )
