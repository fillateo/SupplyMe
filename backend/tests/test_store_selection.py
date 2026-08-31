"""Which database a process is bound to, and how it says so.

There are four answers now — Firestore, its emulator, a JSON file, and memory —
and the wrong one is not loud. A local run silently pointed at production would
write real documents; a demo silently pointed at memory would lose them. So the
selection is tested directly, and so is the note `/api/health` reports, because
that note is the only way to tell from outside which one won.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.adapters import registry
from app.adapters.memory_store import MemoryStore
from app.adapters.snapshot_store import SnapshotStore
from app.config import Settings

from .scripted_llm import ScriptedLLM


class _FakeFirestore:
    """Stands in for `FirestoreStore` so no client is constructed."""

    def __init__(self, project: str, database: str = "(default)") -> None:
        self.project = project
        self.database = database


@pytest.fixture(autouse=True)
def _no_real_firestore(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.adapters.firestore_store as module

    monkeypatch.setattr(module, "FirestoreStore", _FakeFirestore)


def _settings(**overrides: Any) -> Settings:
    base = {
        "maps_api_key": "test-maps-key",
        "smtp_user": "sourcing@example.com",
        "smtp_password": "app-password",
        "project_id": "",
        "use_cloud_infra": False,
        "local_store_path": "",
        "firestore_emulator_host": "",
    }
    return Settings(**{**base, **overrides})


def _build(**overrides: Any) -> registry.Providers:
    return registry.build(_settings(**overrides), llm=ScriptedLLM())


def test_nothing_configured_is_the_in_process_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    providers = _build()

    assert isinstance(providers.store, MemoryStore)
    assert any("do not survive a restart" in note for note in providers.notes)


def test_a_file_path_is_the_file_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    path = tmp_path / "db.json"
    providers = _build(local_store_path=str(path))

    assert isinstance(providers.store, SnapshotStore)
    assert any(str(path) in note for note in providers.notes)


def test_an_emulator_host_wins_and_exports_the_variable_the_client_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    # Set alongside a file path, to pin the precedence rather than leave it to
    # whichever branch happens to come first.
    providers = _build(firestore_emulator_host="127.0.0.1:8085", local_store_path="db.json")

    assert isinstance(providers.store, _FakeFirestore)
    assert providers.store.project == "supplyme-local"
    # The Google client libraries route off this variable, not off Settings.
    import os

    assert os.environ["FIRESTORE_EMULATOR_HOST"] == "127.0.0.1:8085"
    assert any("emulator" in note for note in providers.notes)
    # Local infrastructure, so the bus and scheduler must stay in process.
    assert type(providers.bus).__name__ == "LocalBus"
    assert type(providers.scheduler).__name__ == "LocalScheduler"


def test_the_unprefixed_variable_the_google_libraries_use_is_read_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shell with only `FIRESTORE_EMULATOR_HOST` set must not be ignored.

    The client library would connect to the emulator regardless; if `Settings`
    did not read the same variable, the process would report Firestore while
    talking to a local process.
    """
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:9999")

    assert Settings().firestore_emulator_host == "127.0.0.1:9999"
