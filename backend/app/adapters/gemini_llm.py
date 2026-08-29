"""Gemini via Vertex AI (or the Gemini API when no project is configured).

Three deliberate choices:

* **Structured output only.** Every call declares a Pydantic response schema.
  The agents never parse prose, and untrusted content therefore has no channel
  through which to produce anything but schema-shaped data.
* **Two-tier routing.** Extraction and classification run on the fast model;
  planning and adjudication run on the reasoning model. §55 asks for this and it
  is where most of the cost sits.
* **Resolved, not assumed, model ids.** `resolve_model` probes a preference
  ladder once per process, so the deployment uses the newest model the project
  can actually reach instead of a hardcoded name that may 404.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from ..config import MODEL_LADDER, Settings
from ..security import sanitize

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RESOLVED: dict[str, str] = {}


def _client(settings: Settings) -> genai.Client:
    if settings.use_vertex and settings.project_id:
        return genai.Client(
            vertexai=True, project=settings.project_id, location=settings.location
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
        except Exception as exc:  # noqa: BLE001 - any failure means "try the next one"
            log.debug("model %s unavailable: %s", candidate, exc)
            continue
        _RESOLVED[cache_key] = candidate
        log.info("resolved %s model: %s", cache_key, candidate)
        return candidate

    raise RuntimeError(
        "no Gemini model from the preference ladder is reachable; "
        "set VDS_REASONING_MODEL / VDS_FAST_MODEL explicitly"
    )


class GeminiLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = _client(settings)
        self.calls = 0

    async def structured(
        self,
        *,
        agent: str,
        instruction: str,
        prompt: str,
        schema: type[T],
        untrusted: str | None = None,
        fast: bool = False,
    ) -> T:
        """One model call, returning `schema`. Untrusted text is isolated, not inlined."""
        model = await resolve_model(self._settings, prefer_fast=fast)

        parts = [prompt]
        if untrusted:
            parts.append(sanitize.wrap(untrusted, origin=f"an external source ({agent})"))
        contents = "\n\n".join(parts)

        config = types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2 if fast else 0.4,
            max_output_tokens=8192,
        )

        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=model, contents=contents, config=config
                ),
                timeout=self._settings.llm_timeout_seconds,
            )
        except TimeoutError as exc:
            raise LLMError(f"{agent}: {model} timed out") from exc
        finally:
            self.calls += 1

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "llm_call", extra={"agent": agent, "model": model, "latency_ms": elapsed_ms}
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


class LLMError(RuntimeError):
    """A model call failed in a way the workflow should treat as retryable."""
