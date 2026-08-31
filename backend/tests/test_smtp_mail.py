"""Real delivery over SMTP, with the redirect still in front of it.

The Gmail API path needs an OAuth client that only the Cloud Console can create
and a consent only the mailbox owner can grant. An app password needs neither,
and for proving that outreach genuinely sends, the message that arrives is the
same. These cover the parts that can be wrong without anyone noticing: who the
message says it is from, whether a follow-up threads, and — most importantly —
that the safety valve still stands in front of it.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.adapters.smtp_mail import SmtpMailProvider
from app.config import Settings

SUPPLIER = "contact@premiumparfum.example.com"
TESTER = "operator@example.com"


def settings(**kw) -> Settings:
    base = {"smtp_user": TESTER, "smtp_password": "app-password", **kw}
    return Settings(**base)


@pytest.fixture
def captured(monkeypatch):
    """A provider whose SMTP conversation is recorded instead of dialled."""
    sent: list[EmailMessage] = []
    provider = SmtpMailProvider(settings())
    monkeypatch.setattr(provider, "_deliver", sent.append)
    return provider, sent


class TestItIsOnlyBoundWhenItCanActuallySend:
    def test_credentials_are_required(self):
        assert not SmtpMailProvider(Settings(smtp_user="", smtp_password="")).configured
        assert not SmtpMailProvider(Settings(smtp_user=TESTER, smtp_password="")).configured
        assert SmtpMailProvider(settings()).configured

    def test_gmails_submission_port_is_the_default(self):
        assert Settings().smtp_host == "smtp.gmail.com"
        assert Settings().smtp_port == 587


class TestTheMessageThatGoesOut:
    async def test_the_recipient_and_subject_are_what_the_workflow_asked_for(self, captured):
        provider, sent = captured
        await provider.send(to=SUPPLIER, subject="Quotation request", body="Hello,")
        assert sent[0]["To"] == SUPPLIER
        assert sent[0]["Subject"] == "Quotation request"

    async def test_the_sender_falls_back_to_the_account_that_authenticates(self, captured):
        provider, sent = captured
        await provider.send(to=SUPPLIER, subject="s", body="b")
        assert sent[0]["From"] == TESTER

    async def test_an_explicit_from_address_wins(self):
        provider = SmtpMailProvider(settings(smtp_from="sourcing@example.com"))
        sent: list[EmailMessage] = []
        provider._deliver = sent.append
        await provider.send(to=SUPPLIER, subject="s", body="b")
        assert sent[0]["From"] == "sourcing@example.com"

    async def test_the_body_is_carried_verbatim(self, captured):
        provider, sent = captured
        await provider.send(to=SUPPLIER, subject="s", body="Could you confirm your MOQ?")
        assert "Could you confirm your MOQ?" in sent[0].get_content()

    async def test_a_first_message_reports_its_own_id_as_the_thread(self, captured):
        provider, _ = captured
        result = await provider.send(to=SUPPLIER, subject="s", body="b")
        assert result.provider_message_id.startswith("<")
        assert result.provider_thread_id == result.provider_message_id

    async def test_a_follow_up_stays_in_the_same_conversation(self, captured):
        provider, sent = captured
        first = await provider.send(to=SUPPLIER, subject="s", body="b")
        second = await provider.send(
            to=SUPPLIER, subject="Re: s", body="following up", thread_id=first.provider_thread_id
        )
        assert sent[1]["In-Reply-To"] == first.provider_thread_id
        assert sent[1]["References"] == first.provider_thread_id
        assert second.provider_thread_id == first.provider_thread_id


class TestReadingIsNotPretended:
    async def test_nothing_is_claimed_to_have_been_read(self, captured):
        provider, _ = captured
        assert await provider.fetch_thread("anything") == []
        assert await provider.history(None) == ([], "0")


class TestTheSafetyValveStillStandsInFront:
    async def test_a_supplier_cannot_be_reached_while_the_redirect_is_set(self):
        from app.adapters.mail_redirect import RedirectingMailProvider

        inner = SmtpMailProvider(settings())
        sent: list[EmailMessage] = []
        inner._deliver = sent.append
        provider = RedirectingMailProvider(inner, TESTER)

        await provider.send(to=SUPPLIER, subject="Quotation request", body="Hello,")
        assert sent[0]["To"] == TESTER, "a real supplier was about to be emailed"
        assert SUPPLIER in sent[0]["Subject"]
        assert "did NOT go to the supplier" in sent[0].get_content()

    def test_a_configured_smtp_provider_is_wrapped_by_the_redirect(self):
        from app.adapters.mail_redirect import RedirectingMailProvider
        from app.adapters.registry import _redirected

        notes: list[str] = []
        wrapped = _redirected(
            SmtpMailProvider(settings()), settings(mail_redirect_to=TESTER), notes
        )
        assert isinstance(wrapped, RedirectingMailProvider)
