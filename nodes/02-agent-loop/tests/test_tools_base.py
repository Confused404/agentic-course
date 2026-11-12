"""ToolRegistry + validate_args (coding agent builds these)."""
import json

import pytest

from agentlab.llm.types import ToolUseBlock
from agentlab.tools import Tool, ToolRegistry, validate_args
from shopfront.services import ShopError

S = {"type": "object", "additionalProperties": False, "required": ["order_id", "reason"],
     "properties": {"order_id": {"type": "integer", "minimum": 1}, "reason": {"type": "string", "enum": ["damaged", "other"]},
                    "note": {"type": "string", "minLength": 3, "maxLength": 10}, "amount": {"type": "number"},
                    "flags": {"type": "array", "items": {"type": "string"}}, "ok": {"type": "boolean"}}}


def test_validate_ok():
    assert validate_args(S, {"order_id": 1, "reason": "damaged", "amount": 2.5, "flags": ["a"], "ok": True}) == []


@pytest.mark.parametrize("args,needle", [
    ({"reason": "damaged"}, "order_id"),
    ({"order_id": "4821", "reason": "damaged"}, "integer"),
    ({"order_id": True, "reason": "damaged"}, "integer"),
    ({"order_id": 0, "reason": "damaged"}, "minimum"),
    ({"order_id": 1, "reason": "broken"}, "one of"),
    ({"order_id": 1, "reason": "other", "customer_id": 5}, "customer_id"),
    ({"order_id": 1, "reason": "other", "note": "x"}, "note"),
    ({"order_id": 1, "reason": "other", "flags": [1]}, "flags"),
    ({"order_id": 1, "reason": "other", "amount": True}, "amount"),
])
def test_validate_problems_name_the_field(args, needle):
    problems = validate_args(S, args)
    assert problems and any(needle in p for p in problems), problems


def make():
    def lookup(order_id: int, reason: str = "other"):
        if order_id == 404:
            raise ShopError("NOT_FOUND", "No order #404.")
        if order_id == 500:
            raise RuntimeError("db down")
        return {"order_id": order_id, "b": 2, "a": 1}
    return ToolRegistry([Tool("zeta", "z", {"type": "object", "properties": {}}, lambda: "plain text"),
                         Tool("lookup", "l", {"type": "object", "properties": {"order_id": {"type": "integer"}},
                                              "required": ["order_id"]}, lookup)])


def test_specs_sorted_and_duplicates_rejected():
    assert [s.name for s in make().specs()] == ["lookup", "zeta"]
    with pytest.raises(ValueError):
        ToolRegistry([Tool("a", "", {}, lambda: 1), Tool("a", "", {}, lambda: 2)])


def test_execute_paths():
    r = make()
    ok = r.execute(ToolUseBlock("t1", "lookup", {"order_id": 7}))
    assert not ok.is_error and ok.tool_use_id == "t1" and json.loads(ok.content) == {"a": 1, "b": 2, "order_id": 7}
    assert ok.content.index('"a"') < ok.content.index('"b"'), "sort_keys for stable output"
    assert r.execute(ToolUseBlock("t", "zeta", {})).content == "plain text"
    unknown = r.execute(ToolUseBlock("t", "nope", {}))
    assert unknown.is_error and "lookup" in unknown.content and "zeta" in unknown.content
    bad = r.execute(ToolUseBlock("t", "lookup", {"order_id": "7"}))
    assert bad.is_error and bad.content.startswith("Invalid arguments for lookup")
    nf = r.execute(ToolUseBlock("t", "lookup", {"order_id": 404}))
    assert nf.is_error and json.loads(nf.content)["error"] == "NOT_FOUND"
    crash = r.execute(ToolUseBlock("t", "lookup", {"order_id": 500}))
    assert crash.is_error and "RuntimeError" in crash.content and "Traceback" not in crash.content
