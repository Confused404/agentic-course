"""AGENT-OFF: the compaction prompt (Node 06 YOU_DO task 5).

The summariser model receives this as its system prompt and the older part of the conversation as one user message
(rendered by `agentlab.context.strategies.render_for_summary`). Its reply replaces those messages, wrapped in
<conversation_summary> tags, at the start of the kept history. Whatever it leaves out, the assistant no longer knows.

Write it after you've read TEXTBOOK §4 and the failing traces from the `full` vs `window` runs (task 4).
"""
COMPACTION_PROMPT: str | None = None
