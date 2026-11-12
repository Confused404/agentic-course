# Node 02 Textbook: The agent loop

> **The one-sentence version:** an agent is a model in a loop, calling tools against an environment,
> until it decides to stop or you stop it. Everything in this node is about making that loop
> *correct*, *portable across vendors*, *bounded*, and *observable*. All later nodes stand on it.

## Learning objectives
1. Write a correct agent loop from scratch and state its invariants (message pairing, ordering,
   stop conditions).
2. Design a provider-neutral message model and adapters, and name what is lost or transformed when
   translating between vendor formats.
3. Design tools as an interface for a model: schemas, validation, errors-as-data, side effects, and
   binding to the user's identity.
4. Bound a loop's cost and runtime, and explain why agent cost grows superlinearly with turns.
5. Write a first outcome-based eval suite and explain why 10 cases can't tell you much yet.

---

## §1 What "agent" means here

The term gets used for everything from a chatbot to an autonomous company. In this course:

> An **agent** is a system where a model **decides which actions to take, in what order, and when to stop**,
> by calling tools whose results feed back into its next decision.

Contrast with a **workflow**: the *code* decides the sequence (call model A, then B, then branch on the
output). Both use LLMs; the difference is who controls the flow. Workflows are more predictable and
cheaper; agents handle open-ended tasks where the steps can't be known in advance. Node 09 is about
choosing between them. Here we build the agent primitive.

The four parts:

| Part | Shopfront example | Who controls it |
|---|---|---|
| **Model** | Haiku, GPT-5.6 Luna, Qwen3 8B | the vendor (you choose and configure) |
| **Tools** | `lookup_order`, `issue_refund`, `escalate_to_human` | you |
| **Loop** (the harness) | `run_agent()` | you |
| **Environment** | the Shopfront database, the help center | the world (you seed it for tests) |

The model is the only part you don't write. Agent engineering is everything else.

---

## §2 The loop, line by line

```
messages = [user's message]
loop:
    response = model(system, messages, tool_specs)
    messages.append(assistant: response.content)          # ALL of it, including tool calls and thinking
    if response asked for tools:
        results = [execute(call) for call in response.tool_calls]
        messages.append(user: results)                     # one message, one result per call
        continue
    stop
```

Six lines, and several invariants hidden inside them.

**Invariant 1: the transcript is the state.** The model is stateless between calls. Everything it
"remembers" is in `messages`, which you re-send every turn. If it's not in the transcript, it didn't
happen as far as the model knows. If it *is* in the transcript, the model can use it, including things you'd
rather it ignored. Treat the transcript as an append-only log: editing history mid-conversation
breaks prompt caching (Node 01 §3) and can confuse the model about what it did.

**Invariant 2: every tool call gets exactly one result, in the very next message.** Providers enforce
this. Anthropic rejects a request where a `tool_use` block isn't answered by a `tool_result` with the same
id in the following user message. OpenAI requires a `tool` message for every `tool_call_id` immediately after
the assistant message. Violations are 400 errors, and they're the most common bug in hand-written loops.
They usually appear only on unusual paths: a tool that raised, a call to a tool that doesn't exist,
or a model that issued three calls when you handled one.

**Invariant 3: append the assistant's content verbatim.** Including text that preceded a tool call
("Let me check that…") and, critically, any reasoning blocks. Some vendors require reasoning blocks
to be returned unchanged when the turn involves tools (Node 01 §6). Dropping them causes errors or
degraded behaviour that's hard to trace back.

**Invariant 4: results go back in call order.** When a model makes several calls in one turn
(**parallel tool calls**), return all results in one message, in the same order. You may *execute* them
concurrently if they're independent and side-effect-free. Executing two `issue_refund` calls
concurrently is how double refunds happen (Shopfront's database has a unique index precisely for this).

### What a "turn" costs
Each iteration re-sends the whole transcript. If the transcript grows by roughly `g` tokens per turn from
a base of `b`, the input tokens across `n` turns are about

```
Σ_{t=1..n} (b + g·t)  =  n·b + g·n(n+1)/2      → quadratic in n
```

A 10-turn conversation with a 3K-token system prompt + tools and 800 tokens per turn sends ~74K input
tokens, not 11K. Caching (Node 15) makes the repeated prefix cheap but doesn't remove the growth.
Compaction (Node 06) keeps `g·n` in check. That's why **turn caps** and **budgets** belong in the
loop itself, not in a caller who might forget.

---

## §3 Stop conditions: every way a loop can end

A loop must end in exactly one of a small set of states, and the caller must be told which. "It returned
some text" isn't a result.

| Stop (`LoopResult.stop`) | Cause | What your loop should do |
|---|---|---|
| `end_turn` | model finished and didn't ask for tools (also `stop_sequence`) | return its final text |
| `max_tokens` | output budget exhausted mid-response | **stop and report**. The text may be cut mid-sentence, or a tool call may be incomplete. Don't execute partial tool calls. |
| `refusal` | model declined (safety) | stop, report, don't retry blindly |
| `max_turns` | your cap | stop, report: the agent didn't finish, which is different from finishing badly |
| `budget` | your cost cap (checked before *and* after each call) | stop, report, keep the transcript for debugging |
| `context_window_exceeded` | the transcript no longer fits | stop; compaction (Node 06) is the real fix |
| `other` | anything unexpected (`content_filter`, a `tool_use` with no calls…) | stop and report the raw reason |
| *(not a stop)* `pause_turn` | provider paused a long server-side turn | append and call again; it's a continuation |
| *(exception)* | provider/network failure | propagates to the caller for now; Node 14 adds retries and resumption |

Three design rules:
1. **Distinguish "finished" from "stopped".** A support agent that hit `max_turns` while the customer
   still waits is a failure the caller must handle (apologise, escalate), not a reply.
2. **Never throw away the transcript on a bad stop.** It's your only evidence of what happened.
3. **Leave the transcript resumable.** If the loop stops with tool calls unanswered (a budget stop after a
   `tool_use` turn, a truncated call), append error results for them ("Not executed: budget"). Otherwise
   the *next* user message produces a request with an unanswered tool call, the provider rejects it,
   and that conversation is broken for good.

(`pause_turn` only arises with Anthropic's server-side tools, whose blocks the course's canonical model
doesn't carry. A good ADR question is what it would take to support them.)

---

## §4 Provider-neutral design: the adapter pattern

You'll run the same agent on three vendors. Without an abstraction, vendor details leak everywhere:
`if provider == "anthropic": ... else: ...` in your loop, your tools, your evals. Instead:

```
agent code ── speaks ──▶  agentlab.llm.types  (Message, blocks, ToolSpec, ModelResponse, Usage)
                                  ▲
                    adapters translate at the boundary
                    ▼                                  ▼
          Anthropic Messages API        OpenAI-compatible Chat Completions (OpenRouter, Ollama, OpenAI)
```

**Choosing the canonical model.** The course uses a model shaped like Anthropic's: content is a list of
typed blocks; tool calls and results are blocks. It is a superset of *what this course needs* from both
formats: text, tool calls, tool results and images (which Chat Completions has), plus things Chat
Completions lacks (reasoning blocks with signatures, results containing images, per-block cache
breakpoints). It isn't a superset of everything: it has no slot for Chat Completions' `refusal` field,
mid-conversation system messages, `n` alternative choices, or Anthropic's server-tool blocks. Translating *down* to a less
expressive format is always possible with some loss. Translating *up* from a lossy canonical model is
impossible, which is why you don't pick the lowest common denominator as your canonical model.

**What the OpenAI-compatible adapter must transform** (the lossy direction):

| Canonical | Chat Completions | Note |
|---|---|---|
| `system` (string or blocks) | first message, role `system` | block-level cache flags are dropped |
| assistant `ToolUseBlock` | `tool_calls[].function.arguments` = **JSON string** | `json.dumps(input)` |
| user message of `ToolResultBlock`s | one `role: tool` message **per result**, then any text as a `user` message | ordering matters |
| `ToolResultBlock` with images | text-only tool message + images moved to a following user message | many hosts reject images in tool messages |
| `ThinkingBlock` from another vendor | dropped | foreign signatures are meaningless, or an error |
| `ThinkingBlock` from this vendor (OpenRouter) | `reasoning_details` on the assistant message | round-trips reasoning across tool turns |
| `is_error=True` | content prefixed `ERROR:` | Chat Completions has no error flag |

**And in the other direction (responses → canonical):** parse argument strings (and *capture* failures as
`parse_error` rather than raising: Node 01 E6 showed you they happen), normalise stop reasons (`tool_calls`
→ `tool_use`, `length` → `max_tokens`, and "`stop` but there are tool calls" → `tool_use`), synthesise
tool-call ids if a runtime omits them, and compute uncached input tokens.

**Options (opts) that don't map.** Your loop passes `effort="low"` and `temperature=0.2`. The Anthropic
adapter maps effort to `output_config.effort` and must **drop** temperature (the API rejects it). The
OpenAI-compatible adapter maps effort to `reasoning_effort` (or OpenRouter's `reasoning.effort`) and passes
temperature through *where the model accepts it*. Current OpenAI reasoning models reject it on OpenAI
directly, and OpenRouter drops it silently. Rule: adapters translate what they can, drop what they can't,
and **record what they dropped** (a debug log or an attribute) so a silently ignored knob is discoverable.

**Chat Completions vs the Responses API.** On OpenAI directly, Chat Completions doesn't carry a reasoning
model's reasoning between tool turns. The newer Responses API does (via `previous_response_id`, or
encrypted reasoning items you send back), which measurably helps tool-using reasoning models. OpenRouter's
`reasoning_details` is the Chat Completions workaround. The course uses Chat Completions because every
OpenAI-compatible host speaks it. If you mainly target OpenAI's own models, a Responses adapter is the
better choice, and it slots in behind the same `ChatModel` interface.

**Pure functions at the boundary.** Write each adapter as two pure functions (`to_request(...) -> dict`,
`from_response(dict) -> ModelResponse`) plus a thin method that does the network call between them. You
can test the pure functions exhaustively on recorded payloads, and the network part is three lines.

---

## §5 Tools: an interface designed for a model

A tool has three parts the model sees (**name**, **description**, **input schema**) and one it doesn't
(the **implementation**). The model chooses tools by reading the first three. Node 05 is entirely about
designing them well. Here are the structural rules.

**Errors are data.** When a tool fails, return a `tool_result` with `is_error: true` and a message the
model can act on. Don't raise into the loop.
- `"No order #4812 on this account. Ask the customer to double-check the number."` → the model asks the customer.
- An exception → your loop crashes, or returns a stack trace the model can't use.

Models are good at recovering from clear errors; that recovery is a large part of what makes agents work.

**Validate before executing.** The model's arguments are untrusted input (Node 01 §1). Check required
fields, types and enums against the schema *in your harness*, and turn violations into error results.
Constrained decoding (if your provider applies it to tool arguments) guarantees shape, not semantics: the
service layer still checks that the refund amount is ≤ refundable.

**Identity comes from the session, never from the model.** The support assistant serves one logged-in
customer. If `lookup_order` took a `customer_id` argument, the model could be talked into passing someone
else's ("I'm her husband…"). Instead, **bind** the tools to the session's `customer_id` when you create them.
The model can only ask about order numbers, and the service layer checks ownership. This is the first
instance of a principle that recurs through the course: *capabilities are granted by the harness, not
requested by the model.*

**Side effects deserve friction.** Read tools (`lookup_order`) are cheap to get wrong. Write tools
(`issue_refund`, `cancel_order`, `send_email`) aren't. Design write tools so that:
- invariants are enforced underneath them (the service layer, the DB index),
- they're **idempotent** or at least safe to retry where possible,
- parallel calls can be switched off when it matters (`parallel_tools=False` in the course's opts →
  Anthropic `disable_parallel_tool_use`, OpenAI `parallel_tool_calls: false`),
- every call is audited (Shopfront's `audit_log`), and
- the risky ones can require approval (Node 13/14).

**Deterministic tool order.** Return tool specs in a stable order (e.g. sorted by name). Tools are at
the start of the prompt, so unstable order breaks caching (Node 01 §3).

---

## §6 Bounding the loop

A loop without bounds is a liability. Three independent limits, because each catches different failures:

1. **Turn cap** (`max_turns`) catches the model going in circles (calling the same tool with the same
   arguments, or oscillating between two strategies).
2. **Budget** (`Budget` from `agentlab.costs`) catches expensive *individual* turns (huge tool results,
   long reasoning) that a turn cap wouldn't.
3. **Per-call output cap** (`max_tokens`) bounds latency and cost per turn. Set it with reasoning in mind
   (Node 01 §6): too low and responses are truncated.

When a bound trips, the loop returns a typed stop (§3) and the full transcript. Wall-clock timeouts and
retries come in Node 14.

---

## §7 Observability from the first line

Every model call becomes a `chat` span (tokens, cost, stop reason, content) and every tool execution
an `execute_tool` span (arguments, result, error flag), nested under one `invoke_agent` span. With that
tree you can answer, without trusting the agent's own account of itself:
- Did it call `issue_refund`? With what amount? Did the call succeed?
- Which turn was expensive, and why (input growth? a 6K-token tool result?)
- Where did it go wrong: wrong tool, wrong arguments, misread result, or a correct result followed by a
  wrong conclusion?

That last distinction (**tool selection vs argument vs interpretation errors**) is how you'll debug agents
for the rest of the course.

---

## §8 Your first evals

You'll build evals properly in Node 04. You need some *now*, because from this node on, every change you
make to a prompt, tool or model should be checked against something better than "I tried it once and it
looked fine."

**Grade outcomes, not prose.** For "refund order 4822", the outcome is a row in `refunds` with
`order_id=4822, status='issued'`. Check the database. The agent's reply ("Done! Your refund is on its
way") is the least reliable signal available (Node 01 §8). Complement outcome checks with a few **process**
checks (was `check_refund_eligibility` called before `issue_refund`?) and **reply** checks used sparingly
(does the reply mention the 30-day window? does it *not* leak another customer's item?).

**Fresh environment per case.** Each case starts from a copy of the seeded DB, so one case's refund can't
change another's result.

**Scripted multi-turn users.** Many cases need a second user turn ("Yes, go ahead"). The case lists the
user turns in advance. A *simulated* user (another model) comes in Node 04.

**What 10 cases tell you.** If your assistant passes 8/10, the true pass rate could plausibly be anywhere
from ~50% to ~95% (Node 04 does the statistics). Ten cases are a **smoke detector**: they catch
breakage, not small improvements. Treat them that way.

---

## Design trade-offs

| Decision | Options | Course choice and why |
|---|---|---|
| Canonical message model | lowest common denominator / superset | superset (§4): lossy down-conversion is fine, lossless up-conversion is impossible |
| Tool errors | raise / return as data | data: the model recovers; the loop stays simple |
| Parallel tool execution | sequential / concurrent | sequential by default; concurrency only for read-only tools (§2 inv. 4) |
| Where validation lives | trust provider / harness / service | harness (shape) + service (semantics + invariants) |
| Who supplies identity | model argument / session binding | session binding (§5) |
| Framework or hand-written loop | LangGraph, Agent SDKs, … / your own | your own *now*, to understand it; Node 16 compares frameworks once you can judge them |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 ... tool_use ids were found without tool_result blocks` | a call wasn't answered (unknown tool, exception, partial handling) | every call gets a result, errors included |
| OpenAI 400 about `tool` messages | tool messages not immediately after the assistant message, or a missing id | adapter ordering (§4 table) |
| Agent says it refunded; DB shows nothing | hallucinated result, or the tool errored and the model glossed over it | grade state (§8); read the `execute_tool` span |
| Loop runs until `max_turns` calling the same tool | error message not actionable, or tool result missing the info the model wants | read the tool result as if you were the model; Node 05 |
| Works on Claude, fails on the local model | parse errors, weaker tool selection, truncated context | check `parse_error` blocks and prompt token counts in the trace |
| Costs climb with conversation length | quadratic input growth (§2) | cap turns; compaction in Node 06; caching in Node 15 |
| Reasoning model errors on the 2nd turn | thinking blocks dropped or altered | append assistant content verbatim (§2 inv. 3); adapter round-trips `provider_data` |

## Self-check
1. Your loop handles tool calls by iterating `for call in response.tool_calls` and sending each result as its
   own user message. What breaks, and on which vendor first?
2. Why does `lookup_order` take only `order_id`, not `customer_id`? What attack does that design prevent, and
   which layer still has to check?
3. The model returns `stop_reason="max_tokens"` and the last block is a `tool_use` whose input is `{}`
   with a parse error. Should the loop execute it?
4. Estimate the total input tokens for 15 turns with a 4K base and 1K growth per turn. What does caching
   change, and what doesn't it change?
5. Your adapter receives `effort="high", temperature=0.3`. What should the Anthropic adapter send?
6. The assistant passes 9/10 evals with Model A and 7/10 with Model B. Can you conclude A is better?
7. Name three things you can learn from a trace that you can't learn from the final reply.

<details><summary>Answers</summary>

1. It goes against the documented contract (§2 inv. 2 & 4): all results for a turn belong in the next single
   user message. Some APIs merge consecutive same-role messages, and the OpenAI adapter turns results into
   consecutive `tool` messages anyway, so it may appear to work. It is fragile: it breaks for certain once
   anything (a text block, a missing result) lands between the calls and their results, or in a raw OpenAI
   loop that sends results as `role: user`. Don't rely on vendor leniency.
2. So the model can't be talked into supplying someone else's identity; capabilities are bound by the harness.
   The service layer (`customer_id` ownership check → NOT_FOUND) still enforces it, so that one layer's
   mistake isn't fatal (defence in depth).
3. No. The output was truncated; the call is incomplete. Stop with `max_tokens` and report (or retry with a
   larger budget). Executing partial calls with side effects is dangerous.
4. Σ(4000 + 1000t) for t=1..15 = 60,000 + 120,000 = 180K tokens. Caching makes the repeated prefix much
   cheaper and faster; it doesn't reduce the number of tokens processed or the context-length growth (or
   the risk of crossing a price cliff).
5. `output_config: {effort: "high"}`; drop temperature (and record that it was dropped).
6. No. With n=10, the uncertainty is huge (Node 04), and two different single runs differ by chance. You need
   more cases, more trials, and a paired comparison.
7. Which tools were called with which arguments; whether tool calls succeeded or errored; per-turn tokens and
   cost; whether the model's claim matches the tool results; where in the sequence things went wrong.
</details>

## Socratic review prompt
> Read nodes/02-agent-loop/TEXTBOOK.md and my implementation in agentlab/agent/loop.py. Don't change code.
> Ask me 6 questions, one at a time, probing the loop's invariants and failure paths. For each, ask me to point to the
> exact lines that handle it. If I can't, tell me which test in nodes/02-agent-loop/tests/test_loop.py covers it.
