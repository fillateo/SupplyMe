"""Gemini via Vertex AI (or the Gemini API when no project is configured).

Three deliberate choices:

* **Structured output only.** Every call declares a Pydantic response schema.
  The agents never parse prose, and untrusted content therefore has no channel
  through which to produce anything but schema-shaped data.
* **Two-tier routing.** Extraction and classification run on the fast model;
  planning and adjudication run on the reasoning model, which is where most of
  the cost sits.
* **Resolved, not assumed, model ids.** `resolve_model` probes a preference
  ladder once per process, so the deployment uses the newest model the project
  can actually reach instead of a hardcoded name that may 404.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextvars import ContextVar
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from ..config import MODEL_LADDER, Settings
from ..security import sanitize

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RESOLVED: dict[str, str] = {}

#: Which mission the current task is working for, so a model call made somewhere
#: that does not carry a mission id can still be billed to one. Two callers need
#: this: ADK's own model wrapper, which owns the call stack between `investigate`
#: and the request, and grounded search, which is reached through the Search port
#: and so never sees a mission. Set by the orchestrator for the length of a
#: handler; a ContextVar is what keeps concurrent branches apart.
current_mission: ContextVar[str] = ContextVar("supplyme_mission_id", default="")

#: Vertex returns 429 under sustained parallel load, which is exactly what a
#: fan-out over a dozen vendors produces. This is a queueing problem, not a
#: failure: back off and the same request succeeds. Failing the mission instead
#: would make the system look broken whenever it was busy.
RETRYABLE_MARKERS = (
    "429", "resource_exhausted", "resource exhausted", "quota",
    "503", "unavailable", "500", "internal error", "deadline",
)
MAX_ATTEMPTS = 5
BASE_BACKOFF = 2.0


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in RETRYABLE_MARKERS)


class _Throttle:
    """Process-wide gate on concurrent model requests, with optional pacing.

    Retrying a 429 fixes one request; not making the twelfth simultaneous
    request fixes the storm. Backoff alone cannot, because the fan-out that
    caused the overload is still the thing being retried.

    Built lazily and per event loop: a semaphore belongs to the loop that
    awaits it, and the test suite runs many loops in one process.
    """

    def __init__(self) -> None:
        self._gates: dict[Any, tuple[int, asyncio.Semaphore, asyncio.Lock]] = {}
        self._next_allowed: dict[Any, float] = {}

    def _for_loop(self, limit: int) -> tuple[asyncio.Semaphore, asyncio.Lock]:
        loop = asyncio.get_running_loop()
        found = self._gates.get(loop)
        if found is None or found[0] != limit:
            found = (limit, asyncio.Semaphore(limit), asyncio.Lock())
            self._gates[loop] = found
        return found[1], found[2]

    async def acquire(self, limit: int, interval: float) -> asyncio.Semaphore:
        gate, pace = self._for_loop(limit)
        await gate.acquire()
        if interval > 0:
            loop = asyncio.get_running_loop()
            async with pace:
                now = loop.time()
                wait = self._next_allowed.get(loop, 0.0) - now
                if wait > 0:
                    await asyncio.sleep(wait)
                self._next_allowed[loop] = loop.time() + interval
        return gate


_THROTTLE = _Throttle()

#: Set once at startup so code that does not hold a Settings — notably ADK's own
#: model wrapper — can use the same gate. A module-level value is enough: the
#: gate is per process by definition.
_GATE_CONFIG: dict[str, float] = {"limit": 4, "interval": 0.0}


def configure_throttle(settings: Settings) -> None:
    _GATE_CONFIG["limit"] = settings.max_concurrent_model_calls
    _GATE_CONFIG["interval"] = settings.min_model_call_interval_seconds


async def acquire_model_slot() -> asyncio.Semaphore:
    """Take a slot on the process-wide model gate. Caller must release it."""
    return await _THROTTLE.acquire(int(_GATE_CONFIG["limit"]), _GATE_CONFIG["interval"])


def _client(settings: Settings) -> genai.Client:
    if settings.use_vertex and settings.project_id:
        return genai.Client(
            vertexai=True, project=settings.project_id, location=settings.vertex_location
        )
    return genai.Client(api_key=settings.gemini_api_key or None)


async def resolve_model(settings: Settings, *, prefer_fast: bool = False) -> str:
    """First model on the ladder that this project can actually call."""
    cache_key = "fast" if prefer_fast else "reasoning"
    configured = settings.fast_model if prefer_fast else settings.reasoning_model
    if configured:
        return configured
    if cache_key in _RESOLVED:
        return _RESOLVED[cache_key]

    ladder = MODEL_LADDER
    if prefer_fast:
        ladder = tuple(sorted(ladder, key=lambda m: 0 if "flash" in m else 1))

    client = _client(settings)
    for candidate in ladder:
        try:
            await client.aio.models.generate_content(
                model=candidate,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=8),
            )
        except Exception as exc:
            log.debug("model %s unavailable: %s", candidate, exc)
            continue
        _RESOLVED[cache_key] = candidate
        log.info("resolved %s model: %s", cache_key, candidate)
        return candidate

    raise RuntimeError(
        "no Gemini model from the preference ladder is reachable; "
        "set SUPPLYME_REASONING_MODEL / SUPPLYME_FAST_MODEL explicitly"
    )


class GeminiLLM:
    def __init__(self, settings: Settings, meter: Any = None) -> None:
        self._settings = settings
        configure_throttle(settings)
        self._client = _client(settings)
        self.calls = 0
        #: Records what each call actually cost, from the API's own token counts.
        self.meter = meter

    async def structured(
        self,
        *,
        agent: str,
        instruction: str,
        prompt: str,
        schema: type[T],
        untrusted: str | None = None,
        fast: bool = False,
        mission_id: str = "",
    ) -> T:
        """One model call, returning `schema`. Untrusted text is isolated, not inlined."""
        if self.meter is not None:
            # Checked before the call, so a mission that is already over budget
            # does not spend one more request finding that out.
            self.meter.check(mission_id)
        model = await resolve_model(self._settings, prefer_fast=fast)

        parts = [prompt]
        if untrusted:
            parts.append(sanitize.wrap(untrusted, origin=f"an external source ({agent})"))
        contents = "\n\n".join(parts)

        budget = (
            self._settings.fast_thinking_budget
            if fast
            else self._settings.reasoning_thinking_budget
        )
        config = types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2 if fast else 0.4,
            max_output_tokens=8192,
            # Billed as output. See Settings.fast_thinking_budget.
            thinking_config=(
                types.ThinkingConfig(thinking_budget=budget) if budget >= 0 else None
            ),
        )

        started = time.perf_counter()
        response = await self._generate_with_backoff(agent, model, contents, config)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = _record_usage(self.meter, mission_id, model, response)
        log.info(
            "llm_call",
            extra={
                "agent": agent, "model": model, "latency_ms": elapsed_ms,
                "mission_id": mission_id, **usage,
            },
        )

        parsed: Any = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        text = getattr(response, "text", None)
        if not text:
            raise LLMError(f"{agent}: {model} returned no content")
        try:
            return schema.model_validate_json(text)
        except Exception as exc:
            raise LLMError(f"{agent}: response did not match {schema.__name__}") from exc


    async def _generate_with_backoff(
        self, agent: str, model: str, contents: str, config: Any
    ) -> Any:
        """Call the model, retrying rate limits with exponential backoff and jitter.

        Jitter matters here: without it, a fan-out that all hits 429 at once
        retries in lockstep and hits 429 again.
        """
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self.calls += 1
            gate = await _THROTTLE.acquire(
                self._settings.max_concurrent_model_calls,
                self._settings.min_model_call_interval_seconds,
            )
            try:
                return await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    ),
                    timeout=self._settings.llm_timeout_seconds,
                )
            except TimeoutError as exc:
                last = exc
                if attempt == MAX_ATTEMPTS - 1:
                    raise LLMError(f"{agent}: {model} timed out") from exc
            except Exception as exc:
                last = exc
                if not _is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise LLMError(f"{agent}: {model} failed: {exc}") from exc
            finally:
                # Released before the backoff sleep, so a waiting request takes
                # the slot instead of the gate idling for the whole delay.
                gate.release()

            delay = BASE_BACKOFF * (2**attempt) * (0.5 + random.random())
            log.warning(
                "llm_retry",
                extra={"agent": agent, "model": model, "retry_count": attempt + 1,
                       "error": str(last)[:200], "latency_ms": int(delay * 1000)},
            )
            await asyncio.sleep(delay)

        raise LLMError(f"{agent}: {model} exhausted retries: {last}")


def _record_usage(meter: Any, mission_id: str, model: str, response: Any) -> dict[str, int]:
    """Read the API's own token counts. Absent metadata records zero, not a guess."""
    metadata = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    # Thinking tokens are billed as output and are not always in the candidate count.
    output_tokens += int(getattr(metadata, "thoughts_token_count", 0) or 0)
    if meter is not None:
        meter.record(mission_id, model, input_tokens, output_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


class LLMError(RuntimeError):
    """A model call failed in a way the workflow should treat as retryable."""
