"""Report which Gemini models this project can actually reach.

The hackathon asks for a specific model generation, and a deployment that
silently 404s to an older one is worse than one that says so. Run this before
demoing, and paste the output into the submission if the answer is not what you
expected.

    python scripts/check_models.py                       # Vertex AI, from gcloud ADC
    python scripts/check_models.py --api-key $GEMINI_KEY # Gemini Developer API
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai
from google.genai import types

from app.config import MODEL_LADDER, Settings

EXTRA = ("gemini-3.5-pro", "gemini-3.5-flash", "gemini-3-pro", "gemini-3-flash",
         "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="", help="Google Cloud project (Vertex AI)")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--api-key", default="", help="use the Gemini Developer API instead")
    args = parser.parse_args()

    if args.api_key:
        client = genai.Client(api_key=args.api_key)
        backend = "Gemini Developer API"
    else:
        settings = Settings(project_id=args.project, location=args.location)
        if not settings.project_id:
            print("Pass --project or --api-key.", file=sys.stderr)
            return 2
        client = genai.Client(
            vertexai=True, project=settings.project_id, location=settings.location
        )
        backend = f"Vertex AI ({settings.project_id}/{settings.location})"

    print(f"Backend: {backend}\n")
    candidates = list(dict.fromkeys(MODEL_LADDER + EXTRA))
    reachable = []

    for model in candidates:
        try:
            await client.aio.models.generate_content(
                model=model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=8),
            )
        except Exception as exc:
            reason = str(exc).split("\n")[0][:90]
            print(f"  ✗  {model:<28} {reason}")
            continue
        reachable.append(model)
        marker = " (would be selected)" if model == next(
            (m for m in MODEL_LADDER if m in reachable), None
        ) else ""
        print(f"  ✓  {model}{marker}")

    print()
    if not reachable:
        print("No model is reachable. Check credentials and that the API is enabled.")
        return 1
    preferred = next((m for m in MODEL_LADDER if m in reachable), reachable[0])
    print(f"The service will resolve to: {preferred}")
    print("Override with VDS_REASONING_MODEL / VDS_FAST_MODEL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
