"""Reading replies back out of the mailbox.

The parsing is where this goes wrong quietly. A reply that cannot be matched to
the conversation that caused it is not an error — it is a mission that waits
forever for an answer already sitting in the inbox.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.adapters.imap_mail import _body_of, _header, _thread_of
from app.config import Settings


def reply(**headers: str) -> EmailMessage:
    message = EmailMessage()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content("Minimum order is 500 pcs at Rp 11.000 each.")
    return message


class TestMatchingAReplyToItsConversation:
    """Outreach is redirected while testing, so replies arrive from the test
    mailbox and the sender matches no thread. The mail headers are what survive.
    """

    def test_in_reply_to_is_the_thread(self):
        message = reply(In_Reply_To="<outreach-1@vds>", References="<outreach-1@vds>")
        assert _thread_of(message) == "<outreach-1@vds>"

    def test_references_answers_when_in_reply_to_is_absent(self):
        """Some clients send only References. Its first entry opened the thread,
        which is the id the thread was recorded under."""
        message = reply(References="<outreach-1@vds> <their-reply@example.com>")
        assert _thread_of(message) == "<outreach-1@vds>"

    def test_in_reply_to_wins_over_references(self):
        message = reply(
            In_Reply_To="<outreach-2@vds>",
            References="<outreach-1@vds> <outreach-2@vds>",
        )
        assert _thread_of(message) == "<outreach-2@vds>"

    def test_a_message_that_answers_nothing_has_no_thread(self):
        """Newsletters and cold mail. They must not enter a mission."""
        assert _thread_of(reply(Subject="Welcome to Figma!")) == ""


class TestReadingWhatTheSupplierActuallyWrote:
    def test_plain_text_is_preferred_over_html(self):
        message = EmailMessage()
        message.set_content("MOQ 500, Rp 11.000/pcs.")
        message.add_alternative("<p>MOQ 500, Rp 11.000/pcs.</p>", subtype="html")
        body = _body_of(message)
        assert "MOQ 500" in body
        assert "<p>" not in body

    def test_html_is_used_when_there_is_no_plain_part(self):
        message = EmailMessage()
        message.set_content("<p>MOQ 500</p>", subtype="html")
        assert "MOQ 500" in _body_of(message)

    def test_a_non_utf8_reply_is_read_rather_than_dropped(self):
        """Indonesian suppliers write from clients that are not all UTF-8, and a
        decode error would lose the quote entirely."""
        message = EmailMessage()
        message.set_content("Harga Rp 11.000 per pcs, bisa nego.", charset="iso-8859-1")
        assert "11.000" in _body_of(message)

    def test_an_encoded_header_is_decoded(self):
        message = reply(Subject="=?utf-8?q?Re=3A_Permintaan_penawaran?=")
        assert _header(message, "Subject") == "Re: Permintaan penawaran"

    def test_a_missing_header_is_empty_not_an_error(self):
        assert _header(EmailMessage(), "In-Reply-To") == ""


class TestTheRedirectMailboxMustNotBeTheSendingMailbox:
    """The one configuration that silently breaks the whole demo.

    Outreach is redirected to a mailbox the operator owns, and they answer from
    it as the supplier. If that mailbox is the same one that sends, the reply
    arrives from our own address and is dropped as our own copy — so the mission
    waits forever on an answer already sitting in the inbox, and nothing says
    why. Both example configs used to suggest exactly that pairing.
    """

    def test_a_reply_from_a_second_mailbox_is_read(self):
        from app.adapters.imap_mail import SmtpImapMailProvider

        provider = SmtpImapMailProvider(
            Settings(smtp_user="sourcing@example.com", smtp_password="x", project_id="p")
        )
        assert provider._is_our_own("you@example.com") is False

    def test_a_reply_from_the_sending_mailbox_is_discarded(self):
        from app.adapters.imap_mail import SmtpImapMailProvider

        provider = SmtpImapMailProvider(
            Settings(smtp_user="sourcing@example.com", smtp_password="x", project_id="p")
        )
        assert provider._is_our_own("sourcing@example.com") is True

    def test_the_example_config_does_not_pair_them(self):
        """The docs are the thing that gets this wrong, so assert on the docs."""
        import pathlib
        import re

        text = pathlib.Path(__file__).parents[2].joinpath(
            "terraform/terraform.tfvars.example"
        ).read_text()
        smtp = re.search(r'^smtp_user\s*=\s*"([^"]+)"', text, re.M)
        redirect = re.search(r'^mail_redirect_to\s*=\s*"([^"]+)"', text, re.M)
        assert smtp and redirect
        assert smtp.group(1) != redirect.group(1), (
            "the example pairs the sending mailbox with the redirect target, "
            "which is the one setup where a reply never reaches the mission"
        )


class TestOurOwnMailIsNotASupplierReply:
    """Emailing the mailbox that sends puts a copy in its own inbox. Reading it
    back would have the mission answering itself, and quoting itself as
    evidence."""

    @pytest.fixture
    def provider(self):
        from app.adapters.imap_mail import SmtpImapMailProvider

        return SmtpImapMailProvider(
            Settings(smtp_user="us@example.com", smtp_password="x", project_id="p")
        )

    @pytest.mark.parametrize(
        "sender",
        ["us@example.com", "Us <us@example.com>", "US@EXAMPLE.COM"],
    )
    def test_our_own_address_is_recognised_however_it_is_written(self, provider, sender):
        assert provider._is_our_own(sender) is True

    def test_a_supplier_is_not(self, provider):
        assert provider._is_our_own("sales@vendor.example.com") is False
