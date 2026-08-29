"""Communication agent: email drafting, reply parsing, call planning, call parsing.

This is the only agent permitted to touch the outside world, and the only one
whose output is checked twice — once by its schema and once by the workflow,
which will not send anything the approval policy has not cleared.
"""

from __future__ import annotations

from ..domain.policy import CALL_DISCLOSURE, CALL_PROHIBITIONS, Tool
from .base import Agent
from .schemas import CallExtraction, CallPlan, EmailDraft, QuoteExtraction

EMAIL_INSTRUCTION = """
You write the first email a small buyer sends to a supplier they have never
worked with.

Write it the way a competent founder would: short, specific, and easy to answer.
State what is being made, the quantity, and ask for the missing information as a
list the supplier can reply to line by line. No pleasantries beyond one line, no
marketing language about the buyer's brand, no urgency tactics.

Personalization must come from the supplied facts. If you mention what the
supplier makes, it must be something a source stated, and you must list that
fact in personalization_basis. If you have nothing specific, write a clean
generic email and return an empty personalization_basis — a fabricated
compliment is worse than a plain request.

Never state or imply a budget, a competing quote, or a decision timeline that
was not given to you. Never promise an order.

questions_asked must contain one entry per distinct question in the body,
phrased as the system will later match replies against.
""".strip()

QUOTE_INSTRUCTION = """
You read a supplier's reply and extract what it commits to.

Supplier replies are messy: prices in running prose, quantities in a different
line from the price, mixed languages, numbers written as "8.500" or "8,5rb" or
"Rp 8.500,-". Extract the number the supplier means; when a format is genuinely
ambiguous, leave the field null rather than guessing a magnitude.

line_items maps a component to its per-unit price. When the supplier gives one
price for a bundle, use the key "package" — do not split it yourself.

Set not_a_quote for bounces, out-of-office replies, and messages that decline or
only ask a question back.

answered_questions must contain the questions from our email that this reply
actually answers, and still_unanswered the rest. That split is what decides
whether the system follows up, so do not mark a question answered because the
supplier acknowledged it.

Record commitments verbatim ("we can do 500 as a pilot at Rp 11,000").
""".strip()

CALL_PLAN_INSTRUCTION = f"""
You plan a short phone call to a supplier to obtain specific missing facts.

The opening must identify the caller as an AI assistant in the first sentence.
Use this disclosure, adapted only to fit naturally: "{CALL_DISCLOSURE}"

Constraints on the call, which the opening and questions must respect:
{chr(10).join('- ' + p for p in CALL_PROHIBITIONS)}

Ask at most five questions, each answerable in one sentence, ordered so the
call is still useful if it ends early. Ask only for facts that are actually
missing or disputed — never re-ask something already answered in writing.
""".strip()

CALL_EXTRACT_INSTRUCTION = """
You read a call transcript and record what the supplier said.

Match answers to the questions asked. A question the supplier deflected,
promised to check, or answered with a range that does not resolve it stays in
unanswered. Put numbers in the numeric fields only when the supplier stated
them plainly on the call.
""".strip()


class CommunicationAgent(Agent):
    name = "communication"
    tools = frozenset(
        {Tool.DRAFT_EMAIL, Tool.SEND_EMAIL, Tool.READ_MAIL, Tool.PLACE_CALL, Tool.WRITE_EVIDENCE}
    )
    instruction = EMAIL_INSTRUCTION

    async def draft_email(
        self,
        *,
        vendor_name: str,
        vendor_facts: list[str],
        product: str,
        quantity: int | None,
        unit_spec: str | None,
        market: str | None,
        node_names: list[str],
        missing_fields: list[str],
        mission_id: str = "",
        vendor_id: str | None = None,
    ) -> EmailDraft:
        self.may(Tool.DRAFT_EMAIL)
        prompt = (
            f"Supplier: {vendor_name}\n"
            f"What we want from them: {', '.join(node_names) or 'components for our product'}\n"
            f"Product: {product}\n"
            f"Specification: {unit_spec or 'not stated'}\n"
            f"Quantity for the first batch: {quantity if quantity is not None else 'not stated'}\n"
            f"Market: {market or 'not stated'}\n"
            f"Information we still need: {', '.join(missing_fields) or 'a general quotation'}\n\n"
            "Verified facts about this supplier that may be used for personalization "
            "(use only these, or none):\n"
            + ("\n".join(f"- {f}" for f in vendor_facts) if vendor_facts else "- (none available)")
        )
        return await self.call(
            prompt=prompt, schema=EmailDraft, mission_id=mission_id, vendor_id=vendor_id,
            event_type="email.draft.created",
        )

    async def follow_up_email(
        self,
        *,
        vendor_name: str,
        thread_summary: str,
        unanswered: list[str],
        specific_question: str | None,
        mission_id: str = "",
        vendor_id: str | None = None,
    ) -> EmailDraft:
        self.may(Tool.DRAFT_EMAIL)
        prompt = (
            f"Supplier: {vendor_name}\n"
            "This is a follow-up on an existing thread. Do not repeat what they already "
            "answered, and do not re-introduce the project at length.\n\n"
            f"Thread so far:\n{thread_summary}\n\n"
            f"Still unanswered: {', '.join(unanswered) or 'none'}\n"
            + (f"Specific point to resolve: {specific_question}\n" if specific_question else "")
        )
        return await self.call(
            prompt=prompt, schema=EmailDraft, mission_id=mission_id, vendor_id=vendor_id,
            event_type="followup.required",
        )

    async def extract_quote(
        self, *, body: str, questions_asked: list[str], currency_hint: str = "IDR",
        mission_id: str = "", vendor_id: str | None = None,
    ) -> QuoteExtraction:
        self.may(Tool.READ_MAIL)
        prompt = (
            "Questions we asked this supplier:\n"
            + "\n".join(f"- {q}" for q in questions_asked)
            + f"\n\nLikely currency: {currency_hint}. "
            "Extract what the reply below commits to."
        )
        return await self.call(
            prompt=prompt, schema=QuoteExtraction, untrusted=body, fast=True,
            mission_id=mission_id, vendor_id=vendor_id, event_type="quote.extracted",
            instruction=QUOTE_INSTRUCTION,
        )

    async def plan_call(
        self, *, vendor_name: str, reason: str, missing_fields: list[str],
        conflict_question: str | None, product: str, quantity: int | None,
        mission_id: str = "", vendor_id: str | None = None,
    ) -> CallPlan:
        self.may(Tool.PLACE_CALL)
        prompt = (
            f"Supplier to call: {vendor_name}\n"
            f"Why we are calling instead of emailing: {reason}\n"
            f"Product: {product}, first batch "
            f"{quantity if quantity is not None else 'unspecified'}\n"
            f"Facts still missing: {', '.join(missing_fields) or 'none'}\n"
            + (f"Disagreement to resolve: {conflict_question}\n" if conflict_question else "")
        )
        return await self.call(
            prompt=prompt, schema=CallPlan, mission_id=mission_id, vendor_id=vendor_id,
            event_type="call.required", instruction=CALL_PLAN_INSTRUCTION,
        )

    async def extract_call(
        self, *, transcript: list[dict[str, str]], questions: list[str],
        mission_id: str = "", vendor_id: str | None = None,
    ) -> CallExtraction:
        rendered = "\n".join(
            f"{turn.get('speaker', '?')}: {turn.get('text', '')}" for turn in transcript
        )
        prompt = (
            "Questions the call was meant to answer:\n"
            + "\n".join(f"- {q}" for q in questions)
            + "\n\nTranscript follows."
        )
        return await self.call(
            prompt=prompt, schema=CallExtraction, untrusted=rendered, fast=True,
            mission_id=mission_id, vendor_id=vendor_id, event_type="call.completed",
            instruction=CALL_EXTRACT_INSTRUCTION,
        )
