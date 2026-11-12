"""AGENT-OFF: your COMPACTION_PROMPT (YOU_DO task 5). These only check it exists and is usable; whether it is GOOD
is what the long-conversation evals measure."""
from agentlab.context import prompts
from agentlab.context.strategies import Compaction, make_strategy
from agentlab.tools.lint import lint_prompt


def test_prompt_written():
    p = prompts.COMPACTION_PROMPT
    assert isinstance(p, str) and len(p) >= 300, "write COMPACTION_PROMPT (agentlab/context/prompts.py)"


def test_prompt_is_lint_clean_and_static():
    findings = lint_prompt(prompts.COMPACTION_PROMPT, required_placeholders=())
    assert not [f for f in findings if f.level == "error"], findings
    assert "{today}" not in prompts.COMPACTION_PROMPT, "the summariser prompt has no per-request content"


def test_default_strategy_uses_it():
    from agentlab.llm import fake
    s = make_strategy("compact:5000", model=fake.ScriptedModel([]))
    assert isinstance(s, Compaction) and s.prompt == prompts.COMPACTION_PROMPT
