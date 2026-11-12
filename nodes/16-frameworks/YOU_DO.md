# Node 16: your work

Cost: tasks 2, 3 and 5 are free; the comparison ≈ $0.10–0.30 on paid `fast` (free models: ≈ 150 requests); the
approval drill a few calls.

### 1. [PREDICT] (15 min)
Read TEXTBOOK §1–§4. Predict in `LEARNING_LOG.md`: will the three implementations' pass rates differ on the
regression suite, and by more than noise? Which will use the most input tokens per conversation, and why? Which
needs the fewest lines of code you maintain? For each of the three, where can a crash cause a refund to be issued
twice?

### 2. [AGENT-OFF] convert.py (≤ 45 min)
`to_course_messages`; grader `tests/test_convert.py`. First, **[READ-TRACE]**: run the Pydantic AI port on one
question with a `FunctionModel` (copy `refunding_function` from `tests/test_ports.py`) and print
`run.all_messages()`. Map every part type you see to the course block it becomes, or to "dropped", and say why
each drop is safe. Which piece of information does the course format lose that Pydantic AI keeps, and does any
grader need it?

### 3. [AGENT-OFF] graph_nodes.py (≤ 45 min)
`tools_node`; grader `tests/test_graph_nodes.py` (it uses a real graph). Before coding, write in your log what
happens with this *wrong* version on a turn [`cancel_order`, `issue_refund` (needs approval)]: execute each call in
order, calling `interrupt()` when you reach one that needs approval. Then make the test
`test_side_effects_run_once_across_a_real_resume` fail with it on purpose, and fix it.

### 4. Delegate, then review (≤ 1.5h)
`make new-ticket N=16` → coding agent: *"Implement nodes/16-frameworks/SPEC.md. Follow AGENTS.md. convert.py and
graph_nodes.py are mine; don't write them."*
Review for: the runner hook changes nothing when unused (Node 04–15 tests green); every paid response is charged,
including ones that ended in a tool call or hit the limit; Pydantic AI's cache-inclusive token counts converted;
tool errors returned, never raised; the LangGraph turn cap counts per customer message.

### 5. [READ-TRACE] The hidden parts (≤ 30 min, free)
Read what the Pydantic AI port sends: with a `FunctionModel`, print `info.function_tools`, `info.model_settings`
and the messages it receives. Compare with the native assistant's request (Node 15's recorder, or a Node 01 probe):
tool schemas, system text, settings, anything added. TEXTBOOK §3 lists the defaults the port overrides (concurrent
sync tools, `max_tokens`, the cost estimate); find one more (a retry count, an instruction, a limit) and say what it
would do to a support conversation. Note too that the runner's `assistant_factory` ignores `assistant_opts`: the
ports use prompt v2 and tools v2 by their own defaults, which is why the comparison is fair.

### 6. The comparison (≤ 45 min)
```bash
.venv/bin/python -m agentlab.frameworks compare --model fast
```
**[LOG]** the table against your predictions. For every task where the verdicts differ, open the three
transcripts in `trials.jsonl` and explain the difference (calls, errors, wording). Is any difference bigger than
noise? What do the token and code-line columns tell you that the pass rate doesn't?

### 7. Approvals and crashes, three ways (≤ 1h)
```bash
.venv/bin/python -m agentlab.frameworks graph-start --model fast
# new terminal, later
.venv/bin/python -m agentlab.frameworks graph-show <THREAD>
.venv/bin/python -m agentlab.frameworks graph-resume <THREAD> --model fast --by you
```
Compare with Node 14's `hitl-*` run of the same scenario: what each stored, what you could inspect, what the
customer was told. Then the crash drill **[AGENT-OFF] (20 min)**: write a test that builds the graph with
`graph_port.build_graph` (it takes the registry, so you can wrap one) where `issue_refund` raises Node 14's `Crash`
*after* the real tool wrote the refund (once only), catches it, then resumes the thread (`app.invoke(None,
config)`). Predict first. Count how many times `issue_refund` *executed* and read what the customer is told:
Shopfront's one-refund-per-order rule keeps the money right, so the harm here is a second execution and a reply
saying the refund failed after it went through. Which Node 14 mechanism would have prevented that, and how would you
get the same safety in LangGraph (TEXTBOOK §4)?

### 8. [DECIDE] ADR 0013 (≤ 30 min)
`docs/adr/0013-frameworks.md`: per component (model clients, the loop, tools, approvals, persistence,
observability, evals), keep yours, adopt Pydantic AI, adopt LangGraph, or something else, and why. Include the
comparison table, the drill results, the upgrade/debugging/lock-in costs you saw, and your exit plan: which data
you'd convert and which tests prove the replacement behaves the same.
