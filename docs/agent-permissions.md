# Optional: make your coding agents' permissions match AGENTS.md

AGENTS.md is advisory: a well-behaved agent follows it, a confused one might not. CI's
"protected paths" job catches violations after the fact. For a guard *before* the fact, configure your
coding agents' own permission systems. This is opt-in, because it also restricts you when you work
through the agent.

## Claude Code
Create `.claude/settings.json` in the repo root (or `.claude/settings.local.json` to keep it out of git):
```json
{
  "permissions": {
    "deny": [
      "Edit(nodes/*/tests/**)",
      "Edit(shopfront/tests/**)",
      "Edit(data/**)",
      "Edit(shopfront/seed.py)",
      "Edit(agentlab/llm/types.py)",
      "Edit(agentlab/llm/fake.py)",
      "Bash(make solution:*)",
      "Bash(git merge:*)"
    ]
  }
}
```
Add the AGENT-OFF file of the node you're on (e.g. `"Edit(agentlab/probe/toy_sampler.py)"`) while you write it.
These rules bind the *agent*, not you: you still run `git merge` yourself (e.g. merging shopdev's branch in Node 03
step 6), the agent just can't.
Rule syntax changes over time. If Claude Code rejects a rule, run `/permissions` inside Claude Code to see the
current format.

## OpenCode
OpenCode's `opencode.json` has a `permission` section that can set editing and shell commands to `ask` or
`deny`. Setting `"edit": "ask"` gives you a confirmation before every file change, which works well for
AGENT-OFF nodes. Check the config schema linked in `nodes/00-setup/APPENDIX-2026-11.md` for path-level rules
in your version.

## Why this is also course content
This is the same idea as Node 03's permission gate and Node 13's least-privilege design: rules written
in a prompt are suggestions, and rules enforced by the harness are guarantees.
