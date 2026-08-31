"""Sending for real, to yourself, while a mission is aimed at real companies.

Live outreach is addressed to businesses whose addresses were read off their own
websites. Proving the send path works should not require one of them to receive
a test message, so the provider can be pointed at a single inbox instead. What
must not change is the record: the thread still says who it was written to, or
the mission's own account of itself becomes fiction.
"""

from __future__ import annotations

import pytest

from app.adapters.mail_redirect import RedirectingMailProvider
from app.ports.base import SentMail

TESTER = "operator@example.com"
SUPPLIER = "contact@premiumparfum.example.com"


class FakeMail:
    """Stands in for GmailProvider: records exactly what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str | None]] = []

    async def send(self, *, to, subject, body, thread_id=None, mission_id=""):
        self.sent.append({"to": to, "subject": subject, "body": body, "thread_id": thread_id})
        return SentMail(provider_message_id="msg_1", provider_thread_id="thr_1")

    async def history(self, since_token=None):
        return [], "42"


@pytest.fixture
def redirected():
    inner = FakeMail()
    return inner, RedirectingMailProvider(inner, TESTER)


class TestNothingReachesTheSupplier:
    async def test_the_message_is_delivered_to_the_test_address(self, redirected):
        inner, provider = redirected
        await provider.send(to=SUPPLIER, subject="Quotation request", body="Hello,")
        assert inner.sent[0]["to"] == TESTER

    async def test_the_supplier_address_appears_nowhere_in_the_envelope(self, redirected):
        inner, provider = redirected
        await provider.send(to=SUPPLIER, subject="Quotation request", body="Hello,")
        assert inner.sent[0]["to"] != SUPPLIER

    async def test_a_whitespace_padded_setting_still_addresses_correctly(self):
        inner = FakeMail()
        provider = RedirectingMailProvider(inner, f"  {TESTER}  ")
        await provider.send(to=SUPPLIER, subject="s", body="b")
        assert inner.sent[0]["to"] == TESTER


class TestTheMessageSaysWhatHappened:
    async def test_the_subject_names_the_intended_recipient(self, redirected):
        inner, provider = redirected
        await provider.send(to=SUPPLIER, subject="Quotation request", body="Hello,")
        subject = inner.sent[0]["subject"]
        assert SUPPLIER in subject and "Quotation request" in subject

    async def test_the_body_opens_with_a_warning_and_keeps_the_original(self, redirected):
        inner, provider = redirected
        await provider.send(to=SUPPLIER, subject="s", body="Could you confirm your MOQ?")
        body = inner.sent[0]["body"]
        assert body.startswith("=====")
        assert "did NOT go to the supplier" in body
        assert SUPPLIER in body
        assert "Could you confirm your MOQ?" in body

    async def test_what_was_diverted_can_be_read_back(self, redirected):
        _, provider = redirected
        await provider.send(to=SUPPLIER, subject="s", body="b")
        assert provider.redirected == [{"intended": SUPPLIER, "subject": "s"}]


class TestEverythingElseIsUnchanged:
    async def test_the_thread_id_is_passed_through_so_replies_still_match(self, redirected):
        inner, provider = redirected
        await provider.send(to=SUPPLIER, subject="s", body="b", thread_id="thr_existing")
        assert inner.sent[0]["thread_id"] == "thr_existing"

    async def test_the_provider_still_returns_real_message_ids(self, redirected):
        _, provider = redirected
        sent = await provider.send(to=SUPPLIER, subject="s", body="b")
        assert sent.provider_message_id == "msg_1"
        assert sent.provider_thread_id == "thr_1"

    async def test_reading_mail_is_not_intercepted(self, redirected):
        _, provider = redirected
        assert await provider.history(None) == ([], "42")

    def test_attributes_of_the_wrapped_provider_remain_reachable(self, redirected):
        inner, provider = redirected
        assert provider.sent is inner.sent


class TestItIsOnlyBoundWhenItDoesSomething:
    def test_an_unset_target_leaves_the_provider_alone(self):
        from app.adapters.registry import _redirected
        from app.config import Settings

        inner = FakeMail()
        assert _redirected(inner, Settings(mail_redirect_to=""), []) is inner

    def test_a_real_provider_is_wrapped_and_the_health_note_says_where_mail_goes(self):
        from app.adapters.registry import _redirected
        from app.config import Settings

        notes: list[str] = []
        wrapped = _redirected(FakeMail(), Settings(mail_redirect_to=TESTER), notes)
        assert isinstance(wrapped, RedirectingMailProvider)
        assert any("rather than to the supplier" in note for note in notes)

    def test_the_note_does_not_publish_the_address_it_diverts_to(self):
        """These notes are served by `/api/health`, and a deployed console is public.

        The note has to say mail is being diverted, because an operator who
        cannot tell that from outside eventually writes to a stranger. Saying it
        does not require handing out the mailbox: the domain and the first two
        characters identify it to whoever owns it and to nobody else. The full
        address here published the operator's own inbox to everyone who can
        reach the health endpoint.
        """
        from app.adapters.registry import _redirected
        from app.config import Settings

        notes: list[str] = []
        _redirected(FakeMail(), Settings(mail_redirect_to=TESTER), notes)

        note = " ".join(notes)
        assert TESTER not in note
        assert "op***@example.com" in note
