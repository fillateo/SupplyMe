"""Structured logging.

Cloud Logging reads `severity` and `jsonPayload` from stdout JSON. Emitting the
mission, event and agent ids on every line is what makes "why did the agent pick
this vendor" answerable with a log filter instead of a debugger.
"""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger import json as jsonlogger

#: Fields the workflow attaches to log records; see orchestrator._record.
TRACKED = (
    "mission_id", "agent_run_id", "event_id", "event_type", "tool_call_id",
    "vendor_id", "workflow_state", "latency_ms", "retry_count", "error",
    "agent", "model", "dedup_key", "action", "status", "stage",
)


class CloudLoggingFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):  # type: ignore[override]
        super().add_fields(log_record, record, message_dict)
        log_record["severity"] = record.levelname
        log_record["logger"] = record.name
        for field in TRACKED:
            value = getattr(record, field, None)
            if value is not None:
                log_record[field] = value
        log_record.pop("levelname", None)


def configure(level: str = "INFO", *, json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(CloudLoggingFormatter("%(message)s %(asctime)s"))
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)-7s %(name)-38s %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # These are chatty and say nothing about the mission.
    for noisy in ("httpx", "httpcore", "google.auth", "urllib3", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
