"""Communication agent: email drafting, follow-ups, and reply parsing.

Writing is the only channel this system has, so every question it needs
answered — including settling a disagreement between two sources — has to be
asked in writing. This is the only agent permitted to touch the outside world,
and the only one whose output is checked twice: once by its schema and once by
the workflow, which will not send anything the approval policy has not cleared.
"""

from __future__ import annotations

from ..domain.policy import Tool
from .base import Agent
from .schemas import EmailDraft, QuoteExtraction

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

line_items is one entry per priced COMPONENT, each with its per-unit price. Name
each component the way the components we asked about are named, so the reply can
be matched to the question; where the supplier used their own word for the same
thing, use ours. When the supplier quotes a price at all, this must not be empty.

When the supplier gives a single price covering several components, return one
entry with the component "package" and do not split it yourself — but list in
`covers` every component that one price includes, as the supplier described
them. A bundle whose contents they did not state is reported as uncomparable
rather than guessed at, so `covers` is what decides whether their price can be
compared at all. Do not populate it from inference: if they wrote "set" and
nothing else, leave it empty.

A quantity is never a component, and the two are easy to confuse because they
arrive in the same sentence.

Different components: "botol Rp 8.500, pump Rp 2.500, tutup Rp 1.500" — three
entries, named as we named those components. Their prices genuinely add up to
the cost of one unit.

The same thing at different order quantities: "Rp 11.000 at 500 pcs, Rp 8.500 at
1.000 pcs" — one entry, not two. Pick the rung for the quantity we are buying
and set quantity to it. If no rung matches, pick the one closest to what we are
buying and set quantity to the figure the supplier attached to it. Never return
both: they would look like two components whose prices add up, which costs a
supplier at the sum of their own discount tiers.

Never return nothing merely because the supplier quoted at a quantity we did not
ask about. A price at the wrong quantity is still a price, and reporting it with
its real quantity is what lets it be compared honestly.

Set not_a_quote for bounces, out-of-office replies, and messages that decline or
only ask a question back.

answered_questions must contain the questions from our email that this reply
actually answers, and still_unanswered the rest. That split is what decides
whether the system follows up, so do not mark a question answered because the
supplier acknowledged it.

Record commitments verbatim ("we can do 500 as a pilot at Rp 11,000").
""".strip()
FOLLOW_UP_INSTRUCTION = """
You write a short follow-up on a thread this supplier has already seen.

Do not re-introduce the project, do not thank them at length, and never re-ask
anything they have already answered — a supplier asked the same question twice
stops replying.

When a specific point has to be resolved, that point is the email. Put both
values we hold in front of them and ask which one applies, in one or two
sentences; that is the whole message. Writing is the only way this system can
settle a disagreement, so a vague nudge wastes the only attempt available.

questions_asked must contain one entry per distinct question in the body,
phrased as the system will later match replies against.
""".strip()


class CommunicationAgent(Agent):
    name = "communication"
    tools = frozenset(
        {Tool.DRAFT_EMAIL, Tool.SEND_EMAIL, Tool.READ_MAIL, Tool.WRITE_EVIDENCE}
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
            event_type="followup.required", instruction=FOLLOW_UP_INSTRUCTION,
        )

    async def extract_quote(
        self, *, body: str, questions_asked: list[str], currency_hint: str = "USD",
        order_quantity: int | None = None, components: list[str] | None = None,
        mission_id: str = "", vendor_id: str | None = None,
    ) -> QuoteExtraction:
        self.may(Tool.READ_MAIL)
        # The order quantity is here because suppliers answer with a price
        # ladder — "Rp 11.000 at 500, Rp 8.500 at 1.000" — and which rung
        # applies is the only thing that makes the number comparable.
        wanted = (
            f"We are buying {order_quantity} units."
            if order_quantity
            else "We did not state a quantity."
        )
        # The mission's own component names. Every industry words its invoice
        # lines differently, so the mapping from the supplier's word to ours is
        # done here, where the model can see both, rather than by a table of
        # synonyms that would only ever fit the vertical it was written for.
        vocabulary = (
            "Components this mission is sourcing, and the names to use for them:\n"
            + "\n".join(f"- {c}" for c in components)
            + "\n\n"
            if components
            else ""
        )
        prompt = (
            vocabulary
            + "Questions we asked this supplier:\n"
            + "\n".join(f"- {q}" for q in questions_asked)
            + f"\n\n{wanted} Likely currency: {currency_hint}. "
            "Extract what the reply below commits to."
        )
        return await self.call(
            prompt=prompt, schema=QuoteExtraction, untrusted=body, fast=True,
            mission_id=mission_id, vendor_id=vendor_id, event_type="quote.extracted",
            instruction=QUOTE_INSTRUCTION,
        )
