"""The HTTP surface, exercised against a real mission."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.main import app
from app.config import ApprovalPolicy, Settings

from .conftest import OBJECTIVE
from .fixtures import build_runtime


@pytest.fixture(scope="module")
def client():
    original = deps.startup

    async def scripted(settings=None, **kw):
        # The doubles replace the outside world; deps.startup would
        # otherwise build real providers and demand real credentials.
        from app.api import deps as _deps
        _deps._runtime = build_runtime(
            Settings(approval_policy=ApprovalPolicy.AUTONOMOUS, use_adk_research=False)
        )
        await _deps._runtime.start()
        return _deps._runtime

    deps.startup = scripted
    with TestClient(app) as test_client:
        yield test_client
    deps.startup = original


@pytest.fixture(scope="module")
def mission_id(client: TestClient) -> str:
    response = client.post("/api/missions", json={"objective": OBJECTIVE})
    assert response.status_code == 201
    identifier = response.json()["id"]
    for _ in range(400):
        status = client.get(f"/api/missions/{identifier}").json()["mission"]["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.05)
    return identifier


def test_liveness_does_not_depend_on_the_workflow(client):
    assert client.get("/healthz").status_code == 200


def test_health_reports_which_providers_are_bound(client):
    """The health endpoint names every adapter actually in use.

    It is the only way to tell a deployment that is reading the live web from
    one that is not, and the fastest way to spot a stale revision.
    """
    body = client.get("/api/health").json()
    providers = body["providers"]
    assert set(providers) >= {"store", "bus", "scheduler", "llm", "search", "maps", "mail"}
    # This suite drives the workflow with doubles, and the endpoint says so
    # rather than reporting the names of adapters it is not bound to.
    assert providers["mail"] == "MockMailProvider"


def test_health_names_the_model_and_not_just_the_adapter(client):
    """Which Gemini model is in use has to be answerable without reading code.

    The adapter class name is `GeminiLLM` whichever generation it resolved, and
    the model generation is the one hard technical gate this project is measured
    against. Reporting it here is what lets that be checked from outside.
    """
    model = client.get("/api/health").json()["model"]
    assert set(model) >= {"reasoning", "fast", "backend", "pinned", "ladder"}
    # The ladder is reported so a resolved model can be read against the
    # preference order that produced it.
    assert model["ladder"][0].startswith("gemini-")
    # Nothing is claimed for a tier this process has never called.
    assert model["reasoning"] == "not resolved yet (no call made)"


def test_a_mission_runs_to_completion_over_http(client, mission_id):
    body = client.get(f"/api/missions/{mission_id}").json()
    assert body["mission"]["status"] == "completed"
    assert body["counts"]["vendors"] >= 4
    assert body["counts"]["in_progress"] == 0
    assert len(body["supply_chain"]) >= 5


def test_attempted_outreach_is_not_reported_as_delivered(client, mission_id):
    """`emails_sent` is budget spent; `emails_delivered` is what left the system.

    A live run consumed an outreach slot and then had its SMTP call raise, and
    the mission reported one email sent while none had been delivered. The slot
    is deliberately not given back — a failed send may still have reached the
    supplier — so the two numbers answer different questions and the API says so.
    """
    counts = client.get(f"/api/missions/{mission_id}").json()["counts"]
    assert "emails_sent" in counts and "emails_delivered" in counts
    # Nothing can be delivered that was never attempted.
    assert counts["emails_delivered"] <= counts["emails_sent"]
    # And a reply or a wait presupposes a delivery.
    assert counts["emails_responded"] <= counts["emails_delivered"]
    assert counts["emails_awaiting"] <= counts["emails_delivered"]


def test_vendors_carry_their_trust_breakdown(client, mission_id):
    vendors = client.get(f"/api/missions/{mission_id}/vendors").json()
    assert vendors
    for vendor in vendors:
        assert vendor["trust"]["dimensions"]
        assert all(d["explanation"] for d in vendor["trust"]["dimensions"])


def test_vendor_detail_exposes_the_sources_behind_it(client, mission_id):
    vendors = client.get(f"/api/missions/{mission_id}/vendors").json()
    target = next(v for v in vendors if v["evidence_count"] > 0)
    detail = client.get(f"/api/missions/{mission_id}/vendors/{target['id']}").json()
    assert detail["evidence"]
    assert all(e["evidence_excerpt"] for e in detail["evidence"])


def test_activity_is_the_stored_event_log(client, mission_id):
    activity = client.get(f"/api/missions/{mission_id}/activity").json()
    types = {e["type"] for e in activity}
    assert "mission.created" in types
    assert "quote.extracted" in types
    assert all("recorded_at" in e for e in activity)


def test_the_recommendation_explains_and_rejects(client, mission_id):
    recommendation = client.get(f"/api/missions/{mission_id}/recommendation").json()
    assert recommendation["selections"]
    assert all(s["why"] for s in recommendation["selections"])
    assert recommendation["rejected"]


def test_changing_priorities_reweights_the_ranking(client, mission_id):
    before = client.get(f"/api/missions/{mission_id}/ranking").json()["weights"]
    updated = client.put(
        f"/api/missions/{mission_id}/weights",
        json={"priorities": ["I care more about quality than price"]},
    ).json()["weights"]
    assert updated["price"] < before["price"]
    assert updated["evidence"] > before["evidence"]
    after = client.get(f"/api/missions/{mission_id}/ranking").json()["weights"]
    assert after == pytest.approx(updated)


def test_map_points_only_include_located_vendors(client, mission_id):
    points = client.get(f"/api/missions/{mission_id}/map").json()
    assert points
    assert all(p["lat"] is not None and p["lng"] is not None for p in points)


def test_a_missing_mission_is_404_not_500(client):
    assert client.get("/api/missions/msn_nope").status_code == 404
    assert client.get("/api/missions/msn_nope/vendors").status_code == 404


class TestEventIngress:
    """Pub/Sub and Cloud Tasks must never be handed a retryable error for junk."""

    def test_a_push_with_no_data_is_acknowledged(self, client):
        assert client.post("/events/pubsub", json={"message": {}}).status_code == 204

    def test_an_undecodable_push_is_acknowledged_not_retried(self, client):
        response = client.post(
            "/events/pubsub", json={"message": {"data": "bm90LWpzb24="}}
        )
        assert response.status_code == 204

    def test_a_malformed_task_is_acknowledged(self, client):
        assert client.post("/events/task", json={"nonsense": True}).status_code == 204

    def test_a_valid_push_is_processed(self, client, mission_id):
        import base64

        from app.domain.events import Event, EventType

        event = Event(
            type=EventType.VENDOR_UPDATED, mission_id=mission_id,
            payload={"vendor_id": "ven_missing", "stage": "http-test"},
        )
        encoded = base64.b64encode(event.model_dump_json().encode()).decode()
        response = client.post("/events/pubsub", json={"message": {"data": encoded}})
        assert response.status_code == 204


class TestPushTokenReachesTheEndpoint:
    """The shared secret has to be checkable the way each caller can send it.

    Cloud Tasks sets a header. A Pub/Sub push subscription cannot set headers at
    all, so it can only carry the secret in the endpoint's query string —
    accepting the header alone means every published workflow event comes back
    403 and the deployed mission never advances past `created`.
    """

    TOKEN = "s3cret-push-token"

    @pytest.fixture
    def guarded(self, monkeypatch):
        # The guard reads the environment-derived settings, exactly as the
        # deployed service does, so configure the token the same way.
        from app.config import reset_settings_cache

        monkeypatch.setenv("SUPPLYME_PUBSUB_PUSH_TOKEN", self.TOKEN)
        reset_settings_cache()

        original = deps.startup

        async def scripted(settings=None, **kw):
            # The doubles replace the outside world; deps.startup would
            # otherwise build real providers and demand real credentials.
            from app.api import deps as _deps

            _deps._runtime = build_runtime(
                Settings(approval_policy=ApprovalPolicy.AUTONOMOUS, use_adk_research=False)
            )
            await _deps._runtime.start()
            return _deps._runtime

        deps.startup = scripted
        with TestClient(app) as test_client:
            yield test_client
        deps.startup = original
        reset_settings_cache()

    def test_the_header_form_is_accepted(self, guarded):
        response = guarded.post(
            "/events/task", json={"nonsense": True}, headers={"X-VDS-Token": self.TOKEN}
        )
        assert response.status_code == 204

    def test_the_query_string_form_is_accepted(self, guarded):
        response = guarded.post(
            f"/events/pubsub?token={self.TOKEN}", json={"message": {}}
        )
        assert response.status_code == 204

    def test_no_token_is_rejected(self, guarded):
        assert guarded.post("/events/pubsub", json={"message": {}}).status_code == 403

    def test_a_wrong_token_is_rejected(self, guarded):
        assert guarded.post(
            "/events/pubsub?token=wrong", json={"message": {}}
        ).status_code == 403
        assert guarded.post(
            "/events/pubsub", json={"message": {}}, headers={"X-VDS-Token": "wrong"}
        ).status_code == 403
