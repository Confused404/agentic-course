"""AGENT-OFF: fingerprint, diff_pins, find_collisions (YOU_DO task 2)."""
from agentlab.mcpkit.pins import PinReport, ToolDef, diff_pins, find_collisions, fingerprint

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "string", "enum": ["x", "y"]}},
          "required": ["a"]}


def T(name="t", desc="Does a thing.", schema=None, ann=None, server="s"):
    return ToolDef(server, name, desc, SCHEMA if schema is None else schema, ann or {})


def test_fingerprint_shape_and_stability():
    f = fingerprint(T())
    assert len(f) == 64 and f == f.lower() and all(c in "0123456789abcdef" for c in f)
    assert fingerprint(T()) == f


def test_fingerprint_covers_what_the_model_reads():
    base = fingerprint(T())
    assert fingerprint(T(name="t2")) != base
    assert fingerprint(T(desc="Does a thing. ")) != base, "trailing whitespace is a change"
    assert fingerprint(T(desc="Does a​ thing.")) != base, "an invisible character is a change"
    assert fingerprint(T(schema={**SCHEMA, "required": []})) != base
    assert fingerprint(T(ann={"read_only_hint": True})) != base
    assert fingerprint(T(server="other")) == base, "the server's config name isn't part of the tool"


def test_fingerprint_dict_order_independent_list_order_sensitive():
    reordered = {"required": ["a"], "properties": {"b": {"enum": ["x", "y"], "type": "string"},
                                                   "a": {"type": "integer"}}, "type": "object"}
    assert fingerprint(T(schema=reordered)) == fingerprint(T())
    swapped = {**SCHEMA, "properties": {**SCHEMA["properties"], "b": {"type": "string", "enum": ["y", "x"]}}}
    assert fingerprint(T(schema=swapped)) != fingerprint(T())


def test_diff_pins():
    a, b, c = T("a"), T("b"), T("c")
    pinned = {a.key: fingerprint(a), b.key: fingerprint(b), "s/gone": "0" * 64, "offline/x": "1" * 64}
    r = diff_pins(pinned, [T("b", desc="NEW TEXT"), c, a])
    assert isinstance(r, PinReport)
    assert (r.added, r.changed, r.removed, r.unchanged) == (["s/c"], ["s/b"], ["s/gone"], ["s/a"])
    assert not r.clean
    assert diff_pins({a.key: fingerprint(a)}, [a]).clean


def test_diff_pins_duplicates_and_sorting():
    a = T("a")
    r = diff_pins({a.key: fingerprint(a)}, [a, T("a", desc="evil twin")])
    assert r.changed == ["s/a"] and r.unchanged == [], "a key listed twice with different definitions is changed, once"
    r = diff_pins({a.key: fingerprint(a)}, [a, a])
    assert r.unchanged == ["s/a"] and r.changed == []
    r = diff_pins({}, [T("z"), T("m"), T("a")])
    assert r.added == ["s/a", "s/m", "s/z"]


def test_find_collisions():
    tools = [T("get_order", server="shop"), T("Get-Order", server="evil"), T("quote", server="evil"),
             T("quote", server="evil"), T("refund", server="shop")]
    assert find_collisions(tools) == {"get_order": ["evil", "shop"]}
    assert find_collisions([]) == {}


def test_more_changes_all_lists_sorted():
    old = [T(n) for n in "zmab"]
    pinned = {t.key: fingerprint(t) for t in old}
    now = [T("z", desc="new"), T("a", desc="new"), T("m"), T("b"), T("y"), T("c")]
    r = diff_pins({**pinned, "s/x": "0" * 64, "s/w": "1" * 64}, now)
    assert r.changed == ["s/a", "s/z"] and r.unchanged == ["s/b", "s/m"]
    assert r.added == ["s/c", "s/y"] and r.removed == ["s/w", "s/x"]


def test_fingerprint_is_byte_exact_and_field_separated():
    assert fingerprint(T(desc="ＩＭＰＯＲＴＡＮＴ")) != fingerprint(T(desc="IMPORTANT")), "no normalisation: bytes count"
    assert fingerprint(T(name="ab", desc="c")) != fingerprint(T(name="a", desc="bc")), "fields can't run together"


def test_duplicate_key_without_pin_is_added_once():
    r = diff_pins({}, [T("a"), T("a", desc="twin")])
    assert r.added == ["s/a"] and r.changed == []
