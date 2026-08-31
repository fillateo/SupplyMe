"""Cloud Run entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..logging_setup import configure
from . import deps, routes_events, routes_missions, routes_webhooks

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        json_output=os.environ.get("K_SERVICE") is not None,   # set by Cloud Run
    )
    await deps.startup()
    try:
        yield
    finally:
        await deps.shutdown()


app = FastAPI(
    title="SupplyMe",
    description=(
        "An agentic sourcing workflow: a goal in, a qualified supplier network out. "
        "Every number it reports is traceable to the source it came from."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Read through Settings like every other SUPPLYME_ variable. Reading it
    # straight off the environment here was the one exception, which made
    # app/config.py's claim to be the whole list untrue.
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_missions.router)
app.include_router(routes_events.router)
app.include_router(routes_webhooks.router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> JSONResponse:
    """Liveness only — deliberately does not touch Firestore or Gemini."""
    return JSONResponse({"status": "ok"})
