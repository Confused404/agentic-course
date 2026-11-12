# AGENTS.md: rules for coding agents working in this repo

This file is read by OpenCode and other AGENTS.md-aware tools. `CLAUDE.md` imports it, so Claude Code
follows the same rules. If you are a coding agent: follow every rule below. If you are the learner:
these rules are part of the course. They keep the agent from doing the parts *you* must learn.
CI enforces the most important ones mechanically (see `.github/workflows/grade.yml`, "protected paths").

## What this repo is
A course. `shopfront/` is a small store app (FastAPI + SQLite). `agentlab/` is the agent code the
learner builds, one ticket at a time. Each ticket lives in `nodes/NN-slug/`:
- `README.md`: the ticket (goal, deliverables, done-when).
- `SPEC.md`: **what you (the coding agent) implement.** Your source of truth.
- `YOU_DO.md`: the learner's work. **Never do these tasks.**
- `TEXTBOOK.md`: background. Read the sections SPEC.md points you to.
- `tests/`: the acceptance tests. **Never edit tests to make them pass.**

## Hard rules
1. **Stay inside the ticket.** Only implement what the current node's `SPEC.md` asks. Don't
   implement future nodes, don't refactor unrelated code.
2. **AGENT-OFF work is off-limits**, in every form. That covers:
   - any file or function whose docstring or first comment contains `AGENT-OFF`, and
   - any item tagged `[AGENT-OFF]` in the current node's `YOU_DO.md` or `SPEC.md`, *even if the file
     doesn't exist yet*.

   Don't write it, don't write a "reference version" in a comment, and don't re-implement its behaviour
   elsewhere (a helper, a wrapper, a monkeypatch, a different module) so that other code works without it.
   If your task depends on it, stop, name the missing function and point to its tests. Don't describe
   how to implement it.
3. **Protected paths: do not modify** unless the current SPEC.md explicitly names the file:
   - tests: `nodes/*/tests/**`, `shopfront/tests/**`, any `conftest.py`
   - contracts and fakes: `agentlab/llm/types.py`, `agentlab/llm/fake.py`
   - the app's data and seeded bugs: `shopfront/schema.sql`, `shopfront/seed.py`, `shopfront/content/**`,
     `shopfront/FIXTURES.md`, `shopfront/pricing.py`, `shopfront/reports.py`, `shopfront/search.py`
     (Node 03's coding agent, `shopdev`, fixes those, not you), `data/**` (including gold labels)
   - course plumbing: `pyproject.toml` (pytest options especially), `Makefile`, `.github/**`, `config/models.toml` prices
4. **Never look at reference solutions.** Don't read, fetch, diff or merge `solution/*` branches, and don't
   run `make solution`. That's the learner's escape hatch, not yours.
5. **No test gaming.** Don't detect test runs (`PYTEST_CURRENT_TEST`, `"pytest" in sys.modules`), don't
   special-case fixture IDs or test inputs, don't skip or xfail tests, don't loosen assertions.
6. **No live API calls in tests.** Tests use `agentlab.llm.fake.ScriptedModel`. Live calls only in
   files or tests marked `@pytest.mark.live`.
7. **Every live model call goes through `agentlab.costs.Budget`.** No unbudgeted loops.
8. **Never write secrets** into code, tests, logs or commits. Keys come from `.env` via `agentlab.config`.
9. **Comments explain *why*, not *what*.** When a design choice comes from the textbook, cite it:
   `# why: tool errors are returned to the model, not raised (see nodes/02-agent-loop/TEXTBOOK §5)`.
   Every public function gets a docstring stating its contract (inputs, outputs, errors).
10. **Done means green, except AGENT-OFF tests.** Run `make grade N=<node>` before you say you're done and
    paste the summary. Tests that exercise AGENT-OFF code are *expected to fail* until the learner writes
    it. List them as "expected red (AGENT-OFF)" and don't work around them. If any other test seems wrong,
    say so. Don't change it.
11. **Explain your diff** at the end: files changed, the one design decision you're least sure
    about, and what the learner should read carefully.

## Conventions
- Python 3.12, type hints, dataclasses or pydantic. No new dependencies without saying why.
- Money is integer cents. Time comes from `shopfront.clock`, never `datetime.now()`.
- Tools return JSON-serializable dicts; errors become `ToolResultBlock(is_error=True)` with an
  actionable message, never an exception that crashes the loop.
- Trace with `agentlab.tracing` (`agent_span`, `chat_span`, `tool_span`).

## Useful commands
`make grade N=NN` (offline tests) · `make check` (Shopfront) · `make trace` (latest trace) · `make seed`
