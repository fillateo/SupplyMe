"""Who may do what, and what needs a human first.

Two separate concerns live here on purpose:

* **Tool permissions** are a property of the agent. A research agent that is
  handed a `send_email` tool is a bug, and this table is what makes that bug
  fail loudly instead of sending mail.
* **Approval** is a property of the action. Searching is free and reversible;
  emailing a stranger is neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..config import ApprovalPolicy


class Tool(StrEnum):
    SEARCH_WEB = "search_web"
    READ_PAGE = "read_page"
    QUERY_MAPS = "query_maps"
    WRITE_EVIDENCE = "write_evidence"
    WRITE_VENDOR = "write_vendor"
    DRAFT_EMAIL = "draft_email"
    SEND_EMAIL = "send_email"
    READ_MAIL = "read_mail"
    WRITE_SCORE = "write_score"
    SPEND_MONEY = "spend_money"


#: Explicit allowlist per agent. Anything not listed is denied.
AGENT_TOOLS: dict[str, frozenset[Tool]] = {
    "mission": frozenset({Tool.WRITE_VENDOR}),
    "supply_chain": frozenset(),
    "discovery": frozenset(
        {Tool.SEARCH_WEB, Tool.QUERY_MAPS, Tool.READ_PAGE, Tool.WRITE_VENDOR}
    ),
    "research": frozenset(
        {
            Tool.SEARCH_WEB,
            Tool.READ_PAGE,
            Tool.QUERY_MAPS,
            Tool.WRITE_EVIDENCE,
            Tool.WRITE_VENDOR,
        }
    ),
    "brand_evidence": frozenset(
        {Tool.SEARCH_WEB, Tool.READ_PAGE, Tool.WRITE_EVIDENCE}
    ),
    "communication": frozenset(
        {Tool.DRAFT_EMAIL, Tool.SEND_EMAIL, Tool.READ_MAIL, Tool.WRITE_EVIDENCE}
    ),
    "recommendation": frozenset({Tool.WRITE_SCORE}),
}

#: No agent may spend money. Listed explicitly so the omission is deliberate.
FORBIDDEN_EVERYWHERE: frozenset[Tool] = frozenset({Tool.SPEND_MONEY})


class PermissionError_(PermissionError):
    """Raised when an agent reaches for a tool it was never granted."""


def check(agent: str, tool: Tool) -> None:
    if tool in FORBIDDEN_EVERYWHERE:
        raise PermissionError_(f"tool {tool.value} is not available to any agent")
    allowed = AGENT_TOOLS.get(agent)
    if allowed is None:
        raise PermissionError_(f"unknown agent '{agent}'")
    if tool not in allowed:
        raise PermissionError_(
            f"agent '{agent}' may not use {tool.value} "
            f"(allowed: {', '.join(sorted(t.value for t in allowed)) or 'none'})"
        )


def allowed(agent: str, tool: Tool) -> bool:
    try:
        check(agent, tool)
    except PermissionError_:
        return False
    return True


# --------------------------------------------------------------------------
# Approval boundary
# --------------------------------------------------------------------------


class ActionType(StrEnum):
    SEND_EMAIL = "send_email"
    SEND_FOLLOW_UP = "send_follow_up"
    ACCEPT_QUOTE = "accept_quote"
    PLACE_ORDER = "place_order"


#: Actions that reach outside the system. Everything else runs unattended.
EXTERNAL_ACTIONS = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.SEND_FOLLOW_UP,
        ActionType.ACCEPT_QUOTE,
        ActionType.PLACE_ORDER,
    }
)

#: Actions no policy level may ever auto-approve.
ALWAYS_REQUIRE_HUMAN = frozenset({ActionType.ACCEPT_QUOTE, ActionType.PLACE_ORDER})


@dataclass(frozen=True)
class Decision:
    requires_approval: bool
    reason: str


def approval_for(
    action: ActionType, policy: ApprovalPolicy, *, first_contact_with_vendor: bool = False
) -> Decision:
    """Whether `action` needs a human, under `policy`."""
    if action in ALWAYS_REQUIRE_HUMAN:
        return Decision(True, "financially binding actions always require a human")

    if policy is ApprovalPolicy.AUTONOMOUS:
        return Decision(False, "policy: autonomous")

    if policy is ApprovalPolicy.STRICT:
        return Decision(True, "policy: every outbound action is reviewed")

    # EXTERNAL_ACTIONS: the first approach to a vendor is reviewed; once a human
    # has opened that relationship, follow-ups within it continue unattended.
    if action is ActionType.SEND_EMAIL and first_contact_with_vendor:
        return Decision(True, "first email to this vendor is reviewed")
    if action in EXTERNAL_ACTIONS:
        return Decision(False, "continuing an outreach a human already approved")
    return Decision(False, "internal action")
