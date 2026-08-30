"""The Gmail push endpoint.

This is the one path that makes the product a Taskmaster rather than a batch
job: a supplier answers hours later, Google posts here, and the mission carries
on with nobody watching. The OAuth half needs a live mailbox and is not tested;
everything from the push notification inwards is.
"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.main import app
from app.api.routes_webhooks import _mission_for_thread
from app.config import ApprovalPolicy, Settings
from app.domain.models import EmailThread, ThreadStatus
from app.ports.base import InboundMail

from .fixtures import build_runtime


def push_body(history_id: str = "99") -> dict:
    """The envelope Gmail's Pub/Sub push actually sends: a base64 blob, and no
    indication of what changed beyond a history cursor."""
    payload = json.dumps({"emailAddress": "me@example.com", "historyId": history_id})
    return {"message": {"data": base64.b64encode(payload.encode()).decode()}}


@pytest.fixture
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


class RecordingMail:
    """Stands in for the Gmail adapter: hands back messages and a new cursor."""

    def __init__(self, messages: list[InboundMail]) -> None:
        self.messages = messages
        self.seen_tokens: list[str | None] = []

    async def history(self, since_token=None):
        self.seen_tokens.append(since_token)
        return self.messages, "cursor-after"


def inbound(thread_id: str, sender: str = "sales@vendor.example.com") -> InboundMail:
    return InboundMail(
        provider_message_id="m1", provider_thread_id=thread_id,
        from_address=sender, subject="Re: quotation",
        body="Minimum order is 500 pcs.", received_at="2026-01-01T00:00:00Z",
    )


def test_undecodable_push_is_ignored_not_retried(client: TestClient):
    """Google will redeliver a 5xx forever. A malformed notification is not
    going to become well-formed, so it is accepted and dropped."""
    assert client.post("/webhooks/gmail", json={"message": {"data": "!!not-base64!!"}}).status_code == 204
    assert client.post("/webhooks/gmail", json={}).status_code == 204


def test_push_resumes_the_mission_that_asked(client: TestClient):
    runtime = deps.runtime()
    thread = EmailThread(
        mission_id="msn_alpha", vendor_id="ven_1",
        to_address="sales@vendor.example.com", provider_thread_id="gthread-1",
        status=ThreadStatus.SENT,
    )
    client.portal.call(runtime.repo.save, thread)

    emitted: list = []
    original_emit = runtime.orchestrator.emit

    async def capture(event):
        emitted.append(event)

    runtime.orchestrator.emit = capture
    runtime.providers.mail = RecordingMail([inbound("gthread-1")])
    try:
        assert client.post("/webhooks/gmail", json=push_body()).status_code == 204
    finally:
        runtime.orchestrator.emit = original_emit

    assert [e.type.value for e in emitted] == ["email.received"]
    assert emitted[0].mission_id == "msn_alpha"
    assert emitted[0].payload["body"] == "Minimum order is 500 pcs."


def test_mail_for_nobody_is_ignored(client: TestClient):
    """A mailbox receives more than supplier replies. Anything that matches no
    thread is somebody else's mail and must not enter a mission."""
    runtime = deps.runtime()
    emitted: list = []

    async def capture(event):
        emitted.append(event)

    original_emit = runtime.orchestrator.emit
    runtime.orchestrator.emit = capture
    runtime.providers.mail = RecordingMail([inbound("gthread-unknown", "stranger@example.com")])
    try:
        assert client.post("/webhooks/gmail", json=push_body()).status_code == 204
    finally:
        runtime.orchestrator.emit = original_emit

    assert emitted == []


def test_history_cursor_is_persisted_across_pushes(client: TestClient):
    """Gmail reports that history moved, not what moved. Losing the cursor means
    re-reading the whole mailbox, or missing what arrived in between."""
    runtime = deps.runtime()
    mail = RecordingMail([])
    runtime.providers.mail = mail

    client.post("/webhooks/gmail", json=push_body("100"))
    client.post("/webhooks/gmail", json=push_body("101"))

    assert mail.seen_tokens == [None, "cursor-after"]


def test_address_fallback_prefers_the_thread_still_waiting(client: TestClient):
    """The same supplier can be contacted by two missions. A reply belongs to
    the conversation that is still open, and to the most recent one at that."""
    runtime = deps.runtime()
    settled = EmailThread(
        mission_id="msn_old", vendor_id="ven_1",
        to_address="dual@vendor.example.com", status=ThreadStatus.CLOSED,
    )
    waiting = EmailThread(
        mission_id="msn_new", vendor_id="ven_2",
        to_address="dual@vendor.example.com", status=ThreadStatus.SENT,
    )
    client.portal.call(runtime.repo.save, settled)
    client.portal.call(runtime.repo.save, waiting)

    found = client.portal.call(
        _mission_for_thread, runtime, "", "Sales <dual@vendor.example.com>"
    )
    assert found == "msn_new"


def test_address_fallback_declines_when_every_thread_is_closed(client: TestClient):
    runtime = deps.runtime()
    client.portal.call(runtime.repo.save, EmailThread(
        mission_id="msn_done", vendor_id="ven_9",
        to_address="finished@vendor.example.com", status=ThreadStatus.CLOSED,
    ))
    found = client.portal.call(
        _mission_for_thread, runtime, "", "finished@vendor.example.com"
    )
    assert found is None
