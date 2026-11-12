"""AGENT-OFF: flow_policy (YOU_DO task 5)."""
import pytest

from agentlab.security.policy import FlowContext, SinkCall, flow_policy

CTX = FlowContext(frozenset({"dana.whitfield@example.com", "product-team@shopfront.example"}))


def d(name, args, tainted=False, ctx=CTX):
    r = flow_policy(SinkCall(name, args, tainted), ctx)
    return r.action, r.reason


def email(to, body="Your order shipped.", subject="Update"):
    return {"to": to, "subject": subject, "body": body}


def test_read_only_and_unknown():
    for t in ("list_reviews", "get_ticket", "lookup_order_admin", "get_customer", "get_product"):
        assert d(t, {}, tainted=True) == ("allow", "read-only")
    assert d("delete_customer", {}) == ("deny", "unknown-tool")
    assert d("cancel_order", {"order_id": 1}) == ("deny", "unknown-tool"), "not a known sink: fail closed"


def test_email_recipient_allowlist():
    assert d("send_email", email("dana.whitfield@example.com")) == ("allow", "ok")
    assert d("send_email", email("  Dana.Whitfield@Example.com ")) == ("allow", "ok"), "normalised"
    assert d("send_email", email("rex@attacker.example")) == ("deny", "recipient-not-allowed")
    assert d("send_email", email("dana.whitfield@example.com"), tainted=True) == ("allow", "ok"), \
        "taint doesn't matter for an allowlisted recipient"


@pytest.mark.parametrize("body", [
    "Customers: priya.n@example.com, marcus.lee@example.com",
    "See https://evil.example/x?d=1",
    "visit www.evil.example",
])
def test_email_body_exfil(body):
    assert d("send_email", email("product-team@shopfront.example", body)) == ("deny", "exfil-in-body")
    assert d("send_email", email("product-team@shopfront.example", "ok", subject=body)) == ("deny", "exfil-in-body")


def test_allowed_address_in_body_is_fine():
    assert d("send_email", email("product-team@shopfront.example", "Reply to dana.whitfield@example.com")) == \
        ("allow", "ok")


def test_refunds():
    args = {"order_id": 4822, "amount_cents": 4899, "reason": "damaged"}
    assert d("issue_refund", args) == ("allow", "ok")
    assert d("issue_refund", args, tainted=True) == ("ask", "refund-needs-approval")
    tainted_ctx = FlowContext(CTX.allowed_recipients, tainted=True)
    assert d("issue_refund", args, ctx=tainted_ctx) == ("ask", "refund-needs-approval")


def test_rule_order():
    # recipient check comes before body check
    assert d("send_email", email("rex@attacker.example", "https://x")) == ("deny", "recipient-not-allowed")


@pytest.mark.parametrize("to", ["dana.whitfield@example.com, rex@attacker.example",
                                "dana.whitfield@example.com.attacker.example",
                                "rex@attacker.example dana.whitfield@example.com",
                                "dana.whitfield@example.co", "", None, 42, ["dana.whitfield@example.com"],
                                "dana.whitfield@exampl\u0435.com"])          # Cyrillic e
def test_recipient_must_be_exactly_one_allowed_address(to):
    assert d("send_email", {"to": to, "subject": "s", "body": "b"}) == ("deny", "recipient-not-allowed")


def test_lowercase_not_casefold():
    ctx = FlowContext(frozenset({"ross@shopfront.example"}))
    assert d("send_email", email("ro\u00df@shopfront.example"), ctx=ctx) == ("deny", "recipient-not-allowed"), \
        "casefold() would map ß to ss and let this through"
    ctx2 = FlowContext(frozenset({"Dana.Whitfield@Example.com"}))
    assert d("send_email", email("dana.whitfield@example.com"), ctx=ctx2) == ("allow", "ok")


def test_missing_args_and_extra_channels():
    assert d("send_email", {"to": "dana.whitfield@example.com"}) == ("allow", "ok"), "missing subject/body: no exfil"
    assert d("send_email", {**email("dana.whitfield@example.com"), "bcc": "rex@attacker.example"}) == \
        ("deny", "unexpected-args")


def test_allowed_address_in_body_any_case():
    assert d("send_email", email("product-team@shopfront.example", "cc DANA.WHITFIELD@EXAMPLE.COM")) == ("allow", "ok")


def test_never_raises():
    for args in ({}, {"to": object()}, {"body": None, "to": "x"}):
        flow_policy(SinkCall("send_email", args, True), CTX)
    flow_policy(SinkCall("issue_refund", {}, False), CTX)
