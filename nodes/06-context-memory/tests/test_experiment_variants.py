from agentlab.evals.experiment import Variant


def test_variant_carries_node06_settings():
    v = Variant("x", context="compact:6000:4", memory="on", notes=True)
    o = v.assistant_opts()
    assert (o["context"], o["memory"], o["notes"]) == ("compact:6000:4", "on", True)


def test_fingerprint_unchanged_for_node05_variants_and_sensitive_to_node06():
    import hashlib
    import json
    from agentlab.assistant.prompts import get_prompt
    from agentlab.assistant.tools import make_support_tools
    from shopfront import db
    conn = db.connect(":memory:")
    db.init_schema(conn)
    specs = [s.__dict__ for s in make_support_tools(conn, 0).specs()]
    node05 = hashlib.sha256(json.dumps({"prompt": get_prompt("v1"), "tools": specs, "opts": {}},
                                       sort_keys=True).encode()).hexdigest()[:8]
    base = Variant("a")
    assert base.fingerprint() == node05, "a Node 05 variant keeps the hash in your Node 05 log"
    assert Variant("c", context="window:4").fingerprint() != base.fingerprint()
    assert Variant("d", memory="on").fingerprint() != base.fingerprint()
    assert Variant("e", notes=True).fingerprint() != base.fingerprint()
    assert Variant("f", context="window:4").fingerprint() != Variant("g", context="window:5").fingerprint()
