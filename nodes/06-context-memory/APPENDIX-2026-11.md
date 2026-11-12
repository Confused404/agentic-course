# Appendix (dated 2026-11): provider and tool features for context and memory

These change often. Check the linked docs before relying on any detail; the TEXTBOOK concepts don't depend on them.

## Server-side compaction
**Anthropic** (beta, header `compact-2026-01-12`): add `context_management={"edits": [{"type": "compact_20260112"}]}`
to a Messages request. Options include a `trigger` (`{"type": "input_tokens", "value": N}`), custom `instructions`
for the summary, and `pause_after_compaction`. When it triggers, the response starts with a compaction block; you
append the response to your history as usual and the API uses the block in place of the older messages on the next
call. Docs: platform.claude.com → Build with Claude → Compaction.

**OpenAI** (Responses API): `context_management=[{"type": "compaction", "compact_threshold": N}]` compacts
server-side when the rendered context crosses the threshold; `POST /responses/compact` compacts on demand and returns
a new context window to pass to the next call. The compaction item is **encrypted and opaque**: you can't read what
was kept. Docs: developers.openai.com → Compaction / Context management.

Course view: these save you writing `Compaction`, and the vendor tunes the summary for its own model. You give up
reading the summary (OpenAI), choosing the summariser, portability across vendors, and control over what's kept.
The plant-and-probe suite works unchanged against either; that's how you'd decide.

## Server-side context editing (Anthropic)
Beta header `context-management-2025-06-27`. `clear_tool_uses_20250919` clears the oldest tool results above a
trigger (`trigger`, `keep` recent tool uses, `clear_at_least` tokens, tools to exclude) and replaces them with a
placeholder: the server-side version of `ClearToolResults`. `clear_thinking_20251015` clears old thinking blocks.
The response reports `context_management.applied_edits`. Clearing tool results invalidates the cached prefix from
the cleared point, as in TEXTBOOK §5.

## Memory tools
**Anthropic memory tool** (`{"type": "memory_20250818", "name": "memory"}`): a client-side tool. The model issues
file operations (view, create, edit, delete) on a `/memories` directory, and **your code** executes them against
whatever storage you choose. It's procedural/semantic memory as files, with the same policy questions as §6–§7:
you decide what may be written, and you must scope paths per user.

## Prompt-cache limits that affect this node's numbers
- **Minimum cacheable length**: prefixes shorter than a model-dependent minimum aren't cached at all (on Anthropic,
  1,024–4,096 tokens depending on the model; OpenAI's automatic caching starts at 1,024). Check the current table for
  the models you use. The support assistant's system prompt + tools is under 1K estimated tokens.
- **Lifetime**: Anthropic's default cache TTL is 5 minutes, refreshed on each hit, with a longer (1-hour) option
  that costs more to write. OpenAI's automatic cache is typically cleared after minutes of inactivity. Back-to-back
  eval turns keep caches warm in a way real customers don't.

## Token counting
Anthropic: `POST /v1/messages/count_tokens` (same body as a Messages request). OpenAI Responses: an input-token
counting endpoint (`/responses/input_tokens`). OpenAI-compatible providers via OpenRouter: use `usage` on the
response. Local (Ollama): the response's `prompt_eval_count`. Remember Ollama's default context is 4096 tokens below
24 GB VRAM (Node 00): the long tasks overflow it silently unless you raise `num_ctx`.

## Coding agents
**Claude Code**: auto-compacts near the context limit; `/compact [instructions]` compacts on demand with your
focus; `/clear` starts fresh; memory is the `CLAUDE.md` hierarchy (user, project, local) plus `@imports`; `/memory`
opens it for editing.
**OpenCode**: auto-compaction is on by default (config `"compaction": {"auto": true, ...}` in `opencode.json`,
including how many recent tokens to keep and a buffer); `/compact` (alias `/summarize`) compacts manually; project
instructions live in `AGENTS.md`. Compaction keeps the earlier session messages durably and builds requests from the
latest checkpoint.
Both agents' compaction is exactly the strategy you built: a summary plus recent turns. When a long coding session
"forgets" a decision, you now know where to look.
