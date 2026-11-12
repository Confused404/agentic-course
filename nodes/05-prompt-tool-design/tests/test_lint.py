"""Tool and prompt lint (coding agent builds it)."""
from agentlab.assistant.prompts import SYSTEM_PROMPT_V1
from agentlab.assistant.tools import make_support_tools
from agentlab.llm.types import ToolSpec
from agentlab.tools.lint import lint_prompt, lint_tools


def rules(findings, level=None):
    return {f.rule for f in findings if level is None or f.level == level}


GOOD = ToolSpec("lookup_order", "Look up one order. Use when the customer gives an order number. Returns status, dates "
                "and items.", {"type": "object", "additionalProperties": False, "required": ["order_id"],
                               "properties": {"order_id": {"type": "integer", "description": "e.g. 4821"}}})


def test_good_tool_is_clean():
    assert lint_tools([GOOD]) == []


def test_each_rule_fires():
    bad = [
        ToolSpec("LookupOrder", "short", {"type": "object", "properties": {"x": {}}, "required": ["y"]}),
        ToolSpec("refund", "Refunds an order to the card, for the full value by default.",
                 {"type": "object", "properties": {"reason": {"type": "string"}, "amount": {"type": "integer"}}}),
        ToolSpec("refunds", "Lists refunds. Use when asked about refunds. Returns a list of refunds.",
                 {"type": "array"}),
        ToolSpec("refund", "Duplicate of the refund tool name, which is not allowed at all.", {"type": "object", "properties": {}}),
    ]
    f = lint_tools(bad)
    assert {"name-format", "desc-too-short", "param-no-type", "required-unknown", "schema-not-object",
            "duplicate-name"} <= rules(f, "error")
    assert {"desc-no-when", "desc-no-returns", "param-no-description", "categorical-no-enum", "number-no-unit",
            "additional-properties", "confusable-names"} <= rules(f, "warning")
    assert all(x.where and x.message for x in f)


def test_too_long():
    big = [ToolSpec(f"tool_{i:02d}", "Use when needed. Returns things. " + "x" * 1200,
                    {"type": "object", "additionalProperties": False, "properties": {}}) for i in range(15)]
    assert "tools-too-long" in rules(lint_tools(big), "warning")


def test_v1_support_tools_have_warnings_but_no_errors(conn):
    f = lint_tools(make_support_tools(conn, 9001).specs())
    assert not rules(f, "error") and "param-no-description" in rules(f, "warning")


def test_prompt_lint():
    assert not rules(lint_prompt(SYSTEM_PROMPT_V1), "error")
    assert "missing-placeholder" in rules(lint_prompt("Hello"), "error")
    shout = "Today is {today}. " + "NEVER EVER IGNORE THESE RULES. ALWAYS CHECK. " * 2
    assert {"shouting", "volatile-early"} <= rules(lint_prompt(shout), "warning")
    many = "Intro. " * 200 + " ".join(["You must do it, never skip, always check."] * 3) + " Date {today}."
    assert "absolutes" in rules(lint_prompt(many), "warning") and "volatile-early" not in rules(lint_prompt(many))
    assert "too-long" in rules(lint_prompt("word " * 2000 + "{today}"), "warning")
    acronyms = "Intro. " * 50 + "Return JSON over HTTP for the SKU, in UTC, via the API. Date {today}."
    assert "shouting" not in rules(lint_prompt(acronyms)), "common acronyms aren't shouting"
