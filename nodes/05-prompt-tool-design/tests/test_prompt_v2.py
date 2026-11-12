"""AGENT-OFF: YOUR SYSTEM_PROMPT_V2 (agentlab/assistant/prompts.py). Structure only; quality is measured by evals."""
from agentlab.assistant.prompts import PROMPTS, SYSTEM_PROMPT_V1, get_prompt
from agentlab.tools.lint import lint_prompt


def test_v2_exists_and_is_registered():
    assert "v2" in PROMPTS and get_prompt("v2") != SYSTEM_PROMPT_V1


def test_v2_is_lint_clean():
    findings = lint_prompt(get_prompt("v2"))
    assert not findings, [f"{f.level} {f.rule}: {f.message}" for f in findings]


def test_v2_formats():
    import string
    fields = {f for _, f, _, _ in string.Formatter().parse(get_prompt("v2")) if f is not None}
    assert fields == {"today"}, f"only {{today}} may be a placeholder (escape literal braces as {{{{ }}}}); got {fields}"
    assert "2026-11-01" in get_prompt("v2").format(today="2026-11-01")
