# Appendix (dated 2026-11): harnesses in practice

## Published harness designs
- **Anthropic, "Effective harnesses for long-running agents"** (Nov 26, 2025): an *initializer* agent turns a
  request into persistent artifacts (a structured feature list in JSON with pass flags, a progress file, an init
  script, a git repo); a *coding* agent then works one feature per session, starting each session by reading the
  progress file, the feature list and the git log, and running the tests; it commits and updates progress before
  ending. The coding agent may only flip a feature's pass flag, not edit or delete features.
  https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- **Anthropic, "Harness design for long-running application development"** (Mar 24, 2026): a planner, a generator
  and a separate evaluator. Agents praise their own work; tuning a standalone evaluator to be skeptical was more
  tractable than making the generator self-critical. Harness components encode assumptions about model weaknesses
  and should be re-examined (and removed) as models improve.
  https://www.anthropic.com/engineering/harness-design-long-running-apps
- **The "Ralph" loop** (Geoffrey Huntley): a shell loop feeding the same prompt file to a coding agent forever,
  with state in files and git (`while :; do cat PROMPT.md | <agent>; done`). The effort goes into the prompt, the
  plan file and the checks ("backpressure"), not into agent-to-agent coordination. https://ghuntley.com/ralph/

## Claude Code
- **Hooks** are configured under `"hooks"` in a settings file: `~/.claude/settings.json` (you, all projects),
  `.claude/settings.json` (project, committed), `.claude/settings.local.json` (project, not committed). For this node
  use the workspace's `.claude/settings.local.json`, never the course repo's settings. Handlers receive the event as
  JSON on stdin. **Exit code 2 blocks** on blocking events (PreToolUse, Stop, UserPromptSubmit, …) and stderr goes
  to Claude as the reason; exit code 1 does NOT block (it's a non-blocking error). A Stop hook that exits 2 (or
  returns `{"decision": "block", "reason": …}`) sends Claude back to work; check `stop_hook_active` on stdin to avoid
  loops (Claude Code also caps consecutive stop-hook continuations). The reference lists 30+ events; `/hooks` shows
  what's configured. Docs: https://code.claude.com/docs/en/hooks
  Example stop hook `command` (a shell line; replace PY with the course venv's python, by absolute path). It exits 0
  when Claude Code says this stop was already caused by the hook (`stop_hook_active`), so it can't loop:
  `jq -e '.stop_hook_active' >/dev/null && exit 0; PY -m pytest -q >/dev/null 2>&1 || { echo "tests are failing: fix the code, not the tests" >&2; exit 2; }`
- **Skills**: `.claude/skills/<name>/SKILL.md` (project) or `~/.claude/skills/<name>/SKILL.md` (user), with `name`
  and `description` front matter; Claude sees the descriptions and loads a skill when relevant. Skills follow the
  open Agent Skills format (https://agentskills.io). Docs: https://code.claude.com/docs/en/skills
- **Project memory**: `CLAUDE.md` (Claude Code reads it automatically; many setups point it at `AGENTS.md`).

## OpenCode
- **Skills**: `.opencode/skills/<name>/SKILL.md` (project) or `~/.config/opencode/skills/<name>/SKILL.md`; it also
  reads Claude-compatible `.claude/skills/`. A built-in `skill` tool lists available skills and loads one by name.
  (Older docs and some guides use the singular `skill/` directory: check your version's docs.)
- **Hooks** are plugins: JS/TS modules in `.opencode/plugins/` (project) or `~/.config/opencode/plugins/`, returning
  handlers such as `"tool.execute.before"` (throw an Error to block a call; mutating the input does not block) and
  `"tool.execute.after"`, plus session events. A "refuse to stop while tests fail" rule needs a session event handler
  that sends a follow-up message, so it's more work than Claude Code's Stop hook.
  Docs: https://opencode.ai/docs/plugins/ and https://opencode.ai/docs/skills/
- **Project memory**: `AGENTS.md`.

## Costs and requests (this node)
On `fast` (≈ $0.10 per million input tokens) a 30-turn session costs a few cents; the `single` config's long
session costs more per turn as its context grows. Requests per model for the five-config ablation: ≈ 550 (single
≈ 60, loop and loop+verify ≈ 100 each, loop+verify+eval and full ≈ 150 each with the evaluator). On rate-limited free tiers, run one config at a time.
