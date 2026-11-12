"""AGENT-OFF: verify_token (YOU_DO task 2). Every case is an attack or a mistake seen in real token handling."""
import json

import pytest

from agentlab.authz.tokens import Principal, TokenError, b64url, b64url_decode, issue_token, verify_token

K = b"k" * 32
NOW = 1_800_000_000


def tok(**kw):
    args = dict(sub="customer:9001", audience="shopfront-mcp", scopes=["orders:read", "refunds:write"], now=NOW,
                ttl_s=900, customer_id=9001)
    args.update(kw)
    return issue_token(K, **args)


def code(token, **kw):
    args = dict(audience="shopfront-mcp", now=NOW + 10)
    args.update(kw)
    with pytest.raises(TokenError) as e:
        verify_token(token, K, **args)
    return e.value.code


def forge(header=None, payload=None, key=K):
    import hashlib
    import hmac
    h = b64url(json.dumps(header or {"alg": "HS256", "typ": "JWT"}).encode())
    p = b64url(json.dumps(payload if payload is not None else
                          {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": NOW + 100}).encode())
    s = b64url(hmac.new(key, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{s}"


def test_valid():
    p = verify_token(tok(), K, audience="shopfront-mcp", required_scopes={"orders:read"}, now=NOW + 10)
    assert p == Principal("customer:9001", 9001, frozenset({"orders:read", "refunds:write"}), "shopfront-mcp",
                          NOW + 900)
    assert verify_token(tok(customer_id=None), K, audience="shopfront-mcp", now=NOW).customer_id is None


@pytest.mark.parametrize("bad", ["", "a.b", "a.b.c.d", "..", "a..c", "a.b.c=", "a+b.c.d", 12345, None,
                                 b64url(b"[1]") + "." + b64url(b"{}") + ".sig"])
def test_malformed(bad):
    assert code(bad) in ("malformed", "unsupported_alg")
    if not isinstance(bad, str) or bad.count(".") != 2 or "=" in bad or "+" in bad or ".." in bad or bad == "a.b.c":
        assert code(bad) == "malformed"


def test_not_json_object_header():
    assert code(b64url(b"[1]") + "." + b64url(b"{}") + "." + b64url(b"x")) == "malformed"


@pytest.mark.parametrize("alg", ["none", "None", "hs256", "HS512", "RS256", None])
def test_alg(alg):
    header = {"typ": "JWT"} if alg is None else {"alg": alg, "typ": "JWT"}
    assert code(forge(header=header)) == "unsupported_alg"


def test_alg_none_with_empty_signature_is_not_accepted():
    h = b64url(json.dumps({"alg": "none"}).encode())
    p = b64url(json.dumps({"sub": "x", "aud": "shopfront-mcp", "scope": "refunds:write", "exp": NOW + 99}).encode())
    assert code(f"{h}.{p}.") == "malformed"
    assert code(f"{h}.{p}.AA") == "unsupported_alg"


def test_signature():
    t = tok()
    h, p, s = t.split(".")
    payload = json.loads(b64url_decode(p))
    payload["scope"] += " orders:write"                      # privilege escalation attempt
    assert code(f"{h}.{b64url(json.dumps(payload).encode())}.{s}") == "bad_signature"
    assert code(forge(key=b"other-key" * 4)) == "bad_signature"
    flipped = s[:-2] + ("A" if s[-2] != "A" else "B") + s[-1]
    assert code(f"{h}.{p}.{flipped}") == "bad_signature"


def test_signature_uses_the_bytes_received():
    """Re-serialising the payload before checking would accept a different encoding of the same claims."""
    t = tok()
    h, p, s = t.split(".")
    spaced = b64url(json.dumps(json.loads(b64url_decode(p)), indent=1).encode())
    assert code(f"{h}.{spaced}.{s}") == "bad_signature"


@pytest.mark.parametrize("payload", [
    {"aud": "shopfront-mcp", "scope": "", "exp": NOW + 100},                         # no sub
    {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": "soon"},               # exp not int
    {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": True},                 # bool is not an int here
    {"sub": "x", "aud": 7, "scope": "", "exp": NOW + 100},
    {"sub": "x", "aud": ["a", 7], "scope": "", "exp": NOW + 100},
    {"sub": "x", "aud": "shopfront-mcp", "scope": ["orders:read"], "exp": NOW + 100},
    {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": NOW + 100, "cid": "9001"},
    {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": NOW + 100, "nbf": 1.5},
])
def test_claims_malformed(payload):
    assert code(forge(payload=payload)) == "malformed"


def test_time():
    assert code(tok(), now=NOW + 900) == "expired", "exp is exclusive"
    assert verify_token(tok(), K, audience="shopfront-mcp", now=NOW + 899).sub == "customer:9001"
    assert verify_token(tok(), K, audience="shopfront-mcp", now=NOW + 905, leeway_s=10).sub
    nb = tok(not_before=NOW + 60)
    assert code(nb, now=NOW + 10) == "not_yet_valid"
    assert verify_token(nb, K, audience="shopfront-mcp", now=NOW + 55, leeway_s=5).sub


def test_audience():
    assert code(tok(audience="billing-api")) == "wrong_audience"
    assert code(tok(audience="shopfront-mcp-staging")) == "wrong_audience", "exact match, not prefix"
    assert verify_token(tok(audience=["billing-api", "shopfront-mcp"]), K, audience="shopfront-mcp", now=NOW).sub
    assert code(tok(audience=[])) == "wrong_audience"


def test_scopes():
    assert code(tok(scopes=["orders:read"]), required_scopes={"refunds:write"}) == "insufficient_scope"
    assert code(tok(scopes=["orders:readwrite"]), required_scopes={"orders:read"}) == "insufficient_scope"
    assert verify_token(tok(scopes=[]), K, audience="shopfront-mcp", now=NOW).scopes == frozenset()


def test_check_order():
    """The first failing check wins: an expired token with a bad signature is a bad signature."""
    t = tok(audience="billing-api")
    h, p, s = t.split(".")
    assert code(f"{h}.{p}.{b64url(bytes(32))}", now=NOW + 10_000) == "bad_signature"
    assert code(t, now=NOW + 10_000) == "expired", "expiry is checked before audience"


def _valid_parts():
    return tok().split(".")


def test_truncated_signature_is_bad():
    h, p, s = _valid_parts()
    prefix = b64url(b64url_decode(s)[:1])          # the first byte of the right MAC, canonically encoded
    assert code(f"{h}.{p}.{prefix}") == "bad_signature", "a prefix of the right MAC is not the MAC"


def test_all_required_scopes_needed():
    assert code(tok(scopes=["orders:read"]), required_scopes={"orders:read", "orders:write"}) == "insufficient_scope"


def test_alphabet_padding_and_canonical_form():
    h, p, s = _valid_parts()
    assert code(f"{h}.{p}.{s}=") == "malformed", "padding"
    plus = s.replace("-", "+") if "-" in s else s[:-1] + "+"
    assert code(f"{h}.{p}.{plus}") == "malformed", "standard base64 alphabet"
    last = s[-1]
    alt = next(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
               if c != last and b64url_decode(s[:-1] + c) == b64url_decode(s))
    assert code(f"{h}.{p}.{s[:-1]}{alt}") == "malformed", "non-canonical spelling of the same bytes"


def test_payload_must_be_an_object_even_when_signed():
    assert code(forge(payload=[])) == "malformed"


def test_strict_utf8_and_deep_json():
    h = b64url(json.dumps({"alg": "HS256"}).encode("utf-16"))
    p = b64url(json.dumps({"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": NOW + 99}).encode())
    assert code(f"{h}.{p}.AAAA") == "malformed", "UTF-16 JSON is not a JWT"
    deep = b64url(("[" * 5000).encode())
    assert code(f"{deep}.{p}.AAAA") == "malformed"
    assert code("a" * 9000 + ".b.c") == "malformed", "length bound"


@pytest.mark.parametrize("payload", [
    {"sub": 1, "aud": "shopfront-mcp", "scope": "", "exp": NOW + 100},
    {"sub": "x", "aud": "shopfront-mcp", "scope": "", "exp": NOW + 100, "cid": True},
])
def test_more_claim_types(payload):
    assert code(forge(payload=payload)) == "malformed"


def test_principal_audience_is_the_checked_one():
    p = verify_token(tok(audience=["billing-api", "shopfront-mcp"]), K, audience="shopfront-mcp", now=NOW)
    assert p.audience == "shopfront-mcp"


def test_more_check_order():
    h, p, s = forge(payload={"aud": "shopfront-mcp", "scope": "", "exp": NOW + 100}).split(".")
    assert code(f"{h}.{p}.{b64url(bytes(32))}") == "bad_signature", "signature before claims"
    t = tok(audience="billing-api", scopes=[])
    assert code(t, required_scopes={"orders:read"}) == "wrong_audience", "audience before scopes"


def test_configuration_errors():
    with pytest.raises(ValueError):
        verify_token(tok(), b"short", audience="shopfront-mcp", now=NOW)
    with pytest.raises(TypeError):
        verify_token(tok(), K, audience="shopfront-mcp", now=NOW, required_scopes="orders:read")


def test_scope_separator_is_a_space():
    assert code(tok(scopes=["orders:read\u00a0refunds:write"]), required_scopes={"refunds:write"}) == \
        "insufficient_scope", "a non-breaking space is not a separator"
