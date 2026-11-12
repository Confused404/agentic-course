# Appendix (dated 2026-11): multi-agent systems in practice

## Published evidence
- **Anthropic, "How we built our multi-agent research system"** (June 2025): an orchestrator (Opus 4 lead,
  Sonnet 4 subagents) beat a single Opus 4 agent by 90.2% on an internal research eval. Token usage explained most
  of the performance variance. Agents used about 4× the tokens of chat; multi-agent systems about 15×. Lessons that
  match this node: teach the lead to delegate (objective, output format, tool guidance, boundaries), scale effort
  to query complexity, run subagents in parallel, and judge end states rather than paths.
  https://www.anthropic.com/engineering/multi-agent-research-system
- **Cognition, "Don't Build Multi-Agents"** (June 2025): two principles, *share context* (full traces, not just
  messages) and *actions carry implicit decisions*; parallel writers make conflicting choices.
  https://cognition.ai/blog/dont-build-multi-agents
- **Cognition, "Multi-Agents: What's Actually Working"** (April 2026): a narrower class works in practice, where
  agents contribute intelligence while writes stay single-threaded; e.g. a review agent with no shared context
  checking a coding agent's work. https://cognition.ai/blog/multi-agents-working
- **Cemri et al., "Why Do Multi-Agent LLM Systems Fail?"** (NeurIPS 2025): the MAST taxonomy, 14 failure modes in
  3 families (specification/system design, inter-agent misalignment, task verification), from 1,600+ annotated
  traces across 7 frameworks. https://arxiv.org/abs/2503.13657

## In your coding agents
- **Claude Code**: *subagents* are spawned by the main session through its agent tool, each with its own context,
  system prompt, tool allowlist and optionally model; custom ones are Markdown files with YAML frontmatter in
  `.claude/agents/` (project) or `~/.claude/agents/` (user). *Agent teams* (experimental since Feb 2026, enabled with
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) are separate sessions sharing a task list and messaging each other.
  Docs: https://code.claude.com/docs/en/sub-agents and https://code.claude.com/docs/en/agent-teams
- **OpenCode**: agents have a `mode` of `primary`, `subagent` or `all`; subagents run in child sessions, invoked by
  the primary agent's task/subagent tool or by `@name`. Define them in `.opencode/agents/*.md` (frontmatter + prompt
  body) or in the config file. The config key and field names differ between the current docs and the newer v2 docs
  (`agent` vs `agents`): check yours with `opencode --version` and the matching page.
  https://opencode.ai/docs/agents/
- Both tools' built-in subagents are mostly **read-only explorers**: they search and summarize; the main agent
  decides and edits. That's this node's design (workers read, one agent writes), arrived at independently.

## Frameworks
OpenAI Agents SDK (handoffs; agents as tools), Google ADK (sequential/parallel/loop agents), LangGraph (graphs with
state), CrewAI and AutoGen/AG2 (role-based teams). All implement the shapes in TEXTBOOK §1; none removes the merge
and context problems. Agent-to-agent protocols (A2A, elective E4) standardize how agents in different systems talk,
not whether they should.

## Rate limits
Parallel workers multiply request rate. Provider rate limits are per minute (and on free tiers, per day): a
six-worker fan-out can trip them. Bound concurrency (`max_parallel`), and retry with backoff (Node 14).
