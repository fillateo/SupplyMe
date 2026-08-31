# Backend

The project README is one level up: [../README.md](../README.md). It covers what
the system does, the agent and event architecture, the evidence model, cost, and
security — for the whole project rather than for this directory.

This file used to be a second copy of it. Two copies of the same document
disagree within a week, and this one had already drifted into describing a
feature that no longer exists.

## Running just the backend

```bash
uv venv --python 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"

.venv/bin/python -m pytest -q                  # 462 tests, ~60s, no network
.venv/bin/python scripts/run_mission.py --project YOUR_PROJECT   # a whole mission
.venv/bin/uvicorn app.api.main:app --port 8080
```

`../run.sh` does all of that plus the console, and installs what is missing.

## Layout

| Path | What lives there |
| --- | --- |
| `app/domain/` | The decisions the model is not allowed to make: evidence, conflicts, scoring, quotes, identity, cost, policy |
| `app/agents/` | The ones it is. Six structured calls and one ADK tool loop |
| `app/workflow/` | The orchestrator and its handlers — durability lives here, not in the handlers |
| `app/ports/` | Protocols for every external dependency. The seam the test doubles bind to |
| `app/adapters/` | One implementation of each port per environment |
| `app/api/` | FastAPI: mission routes, Pub/Sub push, Cloud Tasks, Gmail webhook |
| `scripts/` | `run_mission.py`, `check_models.py`, `gmail_auth.py` |
