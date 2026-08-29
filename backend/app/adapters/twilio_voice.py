"""Twilio voice adapter.

Twilio is the telephone line, not the agent. It dials, plays what the
Communication agent wrote, records what the supplier says, and hands the
transcript back — every decision about whether to call, what to ask, and what
the answers mean is made by Gemini and the workflow.

The call is driven by TwiML served from /webhooks/voice/{call_id}: each supplier
answer posts back, the workflow advances one question, and the next TwiML is
generated. That keeps the conversation resumable if the process restarts
mid-call.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

import httpx

from ..config import Settings
from ..ports.base import CallResult

log = logging.getLogger(__name__)


class TwilioVoiceProvider:
    def __init__(self, settings: Settings) -> None:
        self._sid = settings.twilio_account_sid
        self._token = settings.twilio_auth_token
        self._from = settings.twilio_from_number
        self._base_url = settings.public_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def configured(self) -> bool:
        return bool(self._sid and self._token and self._from)

    async def place_call(
        self, *, to: str, opening: str, questions: list[str], call_id: str
    ) -> CallResult:
        if not self.configured:
            return CallResult(
                provider_call_id="", status="failed", error="telephony provider not configured"
            )

        response = await self._client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Calls.json",
            auth=(self._sid, self._token),
            data={
                "To": to,
                "From": self._from,
                "Url": f"{self._base_url}/webhooks/voice/{quote(call_id)}",
                "StatusCallback": f"{self._base_url}/webhooks/voice/{quote(call_id)}/status",
                "StatusCallbackEvent": ["completed", "no-answer", "failed"],
                "MachineDetection": "Enable",
                "Timeout": 25,
            },
        )
        if response.status_code >= 300:
            return CallResult(
                provider_call_id="", status="failed",
                error=f"twilio rejected the call: HTTP {response.status_code}",
            )
        payload = response.json()
        log.info("call_placed", extra={"call_id": call_id, "sid": payload.get("sid")})
        # The transcript arrives via webhook; the workflow resumes on call.completed.
        return CallResult(provider_call_id=payload["sid"], status="dialing")

    async def close(self) -> None:
        await self._client.aclose()


def twiml_for(*, say: str, gather_action: str | None, hangup: bool = False) -> str:
    """One turn of the call. `Gather` with speech input captures the supplier's reply."""
    from xml.sax.saxutils import escape

    body = f'  <Say language="en-US">{escape(say)}</Say>\n'
    if hangup or gather_action is None:
        body += "  <Hangup/>\n"
    else:
        body = (
            f'  <Gather input="speech" speechTimeout="auto" timeout="6" '
            f'action="{escape(gather_action)}" method="POST">\n'
            f"  {body}"
            "  </Gather>\n"
            f'  <Redirect method="POST">{escape(gather_action)}</Redirect>\n'
        )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n{body}</Response>'
