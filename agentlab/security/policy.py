"""AGENT-OFF: the information-flow policy for the ops agent's dangerous tools (Node 08 YOU_DO task 5).

Read TEXTBOOK §5-§6 first. Tests: nodes/08-prompt-injection/tests/test_policy.py. The dataclasses and tool sets
are GIVEN; you write `flow_policy`. The guarded executor calls it before EVERY tool call, in both the `taint` and
the `plan` defences. It's the part of the system that must hold even when the model is fully compromised.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

READ_ONLY = frozenset({"list_reviews", "get_ticket", "lookup_order_admin", "get_customer", "get_product"})
# tools whose RESULTS contain text written by customers or third parties: reviews, tickets, addresses, and the
# name/email a customer typed at sign-up (an attacker can register as "Ignore previous instructions <x@y>")
UNTRUSTED_SOURCES = frozenset({"list_reviews", "get_ticket", "lookup_order_admin", "get_customer"})
SINKS = frozenset({"send_email", "issue_refund"})
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RX = re.compile(r"https?://|www\.", re.I)


@dataclass
class SinkCall:
    name: str
    args: dict
    tainted: bool          # True if untrusted text could have influenced these arguments (see TEXTBOOK §5)


@dataclass
class FlowContext:
    allowed_recipients: frozenset[str]     # derived from the TRUSTED staff request, never from tool results
    tainted: bool = False                  # untrusted content has entered the model's context
    approved: frozenset[str] = field(default_factory=frozenset)   # not used by flow_policy; for the executor


@dataclass
class Decision:
    action: str            # "allow" | "deny" | "ask"  (ask = a human must approve this exact call)
    reason: str            # short id: "read-only", "unknown-tool", "unexpected-args", "recipient-not-allowed",
                           # "exfil-in-body", "refund-needs-approval", "ok"


def flow_policy(call: SinkCall, ctx: FlowContext) -> Decision:
    """Decide whether one tool call may run. Must never raise, whatever is in call.args.

    Requirements (the tests check each; when several apply, the earlier one in this list decides):
    - Read-only tools (READ_ONLY) are always allowed: "read-only".
    - Anything that isn't READ_ONLY or a SINK is denied: "unknown-tool" (fail closed: a tool added tomorrow is
      denied until someone writes its rule).
    - send_email:
        * only the keys to/subject/body; anything else (a future "cc", "bcc") is denied: "unexpected-args";
        * the recipient must be exactly one address, a str, ASCII, and (after strip + lower) a member of
          ctx.allowed_recipients (compared lower-cased): otherwise "recipient-not-allowed". Not casefold(): "ß"
          casefolds to "ss", so "roß@x" would match an allowlisted "ross@x" and then be sent somewhere else;
        * subject and body must not contain an email address (EMAIL_RX) outside the allowlist, or any URL
          (URL_RX): otherwise "exfil-in-body";
        * otherwise "ok".
      (why an allowlist rather than taint: in one agent loop EVERYTHING after reading a review is tainted, so taint
      can't tell the legitimate recipient from the attacker's. The allowlist comes from the staff request, which
      the attacker can't touch. Its limit: if the attacker IS an allowed recipient, it stops nothing; see §5.)
    - issue_refund: "ask" (a human approves this exact call) when call.tainted or ctx.tainted, reason
      "refund-needs-approval"; otherwise allow "ok".
    Return values: Decision("allow" | "deny" | "ask", reason). The executors treat anything else as deny.
    """
    raise NotImplementedError("AGENT-OFF: write flow_policy (Node 08 YOU_DO task 5)")
