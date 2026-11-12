# SPEC: Node 10: three architectures for breadth-heavy questions, and their evals

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§7.
**AGENT-OFF (the learner's; never write or edit it):** `agentlab/multi/reconcile.py::reconcile`. Call it through its
module (`reconcile_module.reconcile`) so tests can substitute it. Its tests stay red until the learner writes it.
**GIVEN (don't rewrite):** `agentlab/multi/tasks.py` (`MultiTask`, `TASKS`, gold functions, `grade`, `_stats`),
`agentlab/multi/tools.py` (`analytics_tools(conn, scope)`, `categories(conn)`, `MAX_STATS_IDS`), and the
`WorkerReport` / `Reconciled` dataclasses in `reconcile.py`.

## Files
```
create  agentlab/multi/architectures.py   (1-4)
create  agentlab/multi/evals.py           (5)
create  agentlab/multi/__main__.py        (6)
```
Nothing outside `agentlab/multi/` changes. `make grade-upto N=10` must stay green for 00–09.

## 1. Metering and results (`architectures.py`)
```python
@dataclass
class CallRecord: agent: str; input_tokens: int; output_tokens: int   # input = usage.total_input (whole prompt)
class Metered:            # wraps a ChatModel; .provider/.model copied; complete(**kw) calls the inner model and
                          # appends a CallRecord under a lock (workers run in threads)
@dataclass
class MultiResult:
    arch: str; answer: Any = None; cost_usd: float = 0.0; latency_s: float = 0.0
    calls: list[CallRecord] = []; agents: int = 0; delegations: int = 0
    missing_shards: list[str] = []      # still missing when the answer was given
    conflicts: int = 0; error: str | None = None
    provider_errors: int = 0            # failures caused by the provider (agentlab.evals.runner.error_kind == "provider")
    transcripts: dict[str, list] = {}   # agent name -> messages as dicts (agentlab.llm.types.to_dict)
    input_tokens / output_tokens        # properties: sums over calls
    peak_context                        # property: max input_tokens over calls (0 if none)
    def tokens_by_role(self) -> dict    # role = agent name before ":" ("lead", "worker", "single", "reducer")
def submit_tool(out: dict) -> Tool      # submit_answer(answer): schema {"answer": {description only, no type}};
                                        # stores into out["answer"] (a JSON string is json.loads'ed once);
                                        # a second call is a ToolError containing "already submitted";
                                        # side_effects=True
```
Agent names: `"single"`, `"lead"`, `"reducer"`, `"worker:<shard>#<tag><i>"`.

## 2. Workers
```python
WORKER_SYSTEM: str      # do exactly the brief, for your shard only; product_stats takes ≤10 ids; call report once;
                        # report tool data, not estimates; say in notes what was impossible
def run_worker(model, conn, shard, brief, budget, max_turns=12) -> (WorkerReport, transcript)
    # ONE user message: f"{brief}\n\nYour shard: category {shard!r}." and nothing else (fresh context);
    # tools: analytics_tools(conn, [shard]) + report(items: object, notes?: string) (once; second call ToolError);
    # never reported -> WorkerReport(shard, {}, "worker never reported (stop=...)", ok=False)
def run_workers(worker_factory, conn, tasks: list[(shard, brief)], budget, log, lock, transcripts, tag,
                max_parallel=6, worker_turns=12) -> list[WorkerReport]
    # ThreadPoolExecutor; a FRESH model per worker from the factory, wrapped in Metered(name=worker:...);
    # an exception in a worker -> ok=False report with the error in notes and error_kind=error_kind(e) (never
    # propagates); transcripts[name] = transcript; results in task order; run each worker under
    # contextvars.copy_context().run(...) so its trace spans nest under the caller's
```

## 3. The three architectures
```python
SINGLE_SYSTEM: str      # systematic coverage, careful arithmetic (pool averages with rating_sum), submit once
def run_single(model, conn, task, budget=None, max_turns=40) -> MultiResult
    # tools: analytics_tools(conn) (unscoped) + submit_answer; agents=1; no answer -> error "no answer submitted (stop=…)"
    # an exception from the loop (other than BudgetExceeded, which propagates) -> error f"{type}: {msg}", and
    # provider_errors += 1 if error_kind(e) == "provider"; calls/cost/latency are still filled in (partial accounting).
    # Same rule for the lead's loop and the reducer call below.

LEAD_SYSTEM: str        # the lead can't query data; what a worker sees (only its brief, one shard); what a brief must
                        # contain (objective, definitions, output shape keyed by SKU; combinable fields; each shard
                        # once per call); delegate result fields;
                        # re-delegate missing shards (≤2 times), never guess them; submit once
def run_orchestrator(lead, worker_factory, conn, task, budget=None, max_turns=12, max_delegations=3,
                     max_parallel=6, worker_turns=12) -> MultiResult
    # lead tools: list_categories (from analytics_tools) + delegate + submit_answer
    # delegate(tasks=[{shard, brief}]) -> ToolError when (message must contain the quoted word):
    #   delegation limit reached ("limit"); tasks empty ("empty"); more tasks than shards; a task isn't
    #   {shard: str, brief: str}; unknown shard ("Unknown shard", and list the shards); brief < 20 chars after
    #   strip ("too short"); the same shard twice in one call ("twice")
    # else: run_workers(...); rec = reconcile_module.reconcile([shards in this call], reports);
    #   covered |= delegated shards not in rec.missing_shards; returns
    #   {results: rec.merged, missing_shards, conflicts, duplicates, notes, not_yet_covered: [all shards not covered]}
    #   provider_errors += failed reports with error_kind "provider"
    # result: agents = 1 + workers started; delegations; missing_shards = not yet covered at the end;
    #   conflicts = total over delegations; transcripts include "lead"

MAPREDUCE_BRIEF: str    # the overall question, "answer it ONLY for category {shard}", items keyed by SKU with
                        # reviews, rating_sum, avg_rating, units_90d, stock, reorder_level, active; partial answer in notes
REDUCER_SYSTEM: str     # combine using only the given data; JSON only: {"answer": ...}
def run_map_reduce(worker_factory, reducer, conn, task, budget=None, max_parallel=6, worker_turns=12) -> MultiResult
    # one worker per category (categories(conn)), in parallel; reconcile; if shards are missing, run ONLY those
    # once more and reconcile all reports again; then ONE reducer call (tools=None, max_tokens=2048) with the
    # question and JSON {results, partial_answers (rec.notes), missing_shards, conflicts}; parse (strip code fences)
    # -> answer, unparseable -> error "reducer output unparseable"; budget check/charge around the reducer call;
    # the reducer is metered as agent "reducer"; agents = workers started + 1; delegations = rounds of workers (1 or 2);
    # provider_errors = shards still missing whose last report had error_kind "provider";
    # transcripts["reducer"] = [to_dict(user message), to_dict(assistant message)]
def parse_arch(spec) -> (name, args)    # "single:A" | "orch:LEAD:WORKER" | "mapreduce:WORKER:REDUCER", each part a
                                        # model ALIAS (specs like ollama:qwen3:8b contain ":" and can't be used:
                                        # add an alias); optional "@label" suffix (e.g. orch:fast:fast@brief2) for
                                        # comparing variants; empty parts, empty label or anything else -> ValueError
def run_arch(spec, task, get_model, conn, budget=None, max_parallel=6) -> MultiResult   # result.arch = spec (label
                                        # included); max_parallel passed to orch and mapreduce
```
`cost_usd` = budget spent during the run (0 without a budget). `latency_s` = wall time of the whole run.

## 4. Notes
- Budget: `agentlab.costs.Budget` is already thread-safe; share one across workers. `run_agent` turns a budget stop
  into `stop="budget"`; workers then report ok=False. Don't add retries for budget stops. Parallel workers each pass
  `check()` before their call, so a run can overshoot the cap by up to `max_parallel` calls: that's expected.
- The database connection is shared by worker threads. The GIVEN tools serialise every query with a lock (sqlite3's
  statement cache is not thread-safe); don't query `conn` from worker threads outside those tools.
- Don't let a `ScriptedModel` be shared across threads; the tests give each worker its own fake.

## 5. `evals.py`
```python
def to_trial(task, r: MultiResult, conn, k=0) -> Trial   # keyword args only; model=r.arch; verdict: pass if
    # grade() passes AND r.missing_shards is empty (detail mentions "missing" otherwise), "error" if r.answer is
    # None, else fail; a non-pass with r.provider_errors > 0 -> verdict "error", error_kind "provider";
    # grades=[GradeResult("gold", …, detail[:500])]; turns=len(r.calls); tags=[task.answer_kind];
    # extra={input_tokens, output_tokens, peak_context, tokens_by_role, agents, delegations, missing_shards,
    # conflicts, provider_errors}
def run_multi(tasks, archs, get_model, conn, *, trials=1, budget=None, out_dir=None, max_parallel=6) -> list[Trial]
    # trial -> task -> arch; BudgetExceeded propagates; other exceptions -> error trial (error_kind from Node 04)
    # whose cost_usd is the budget spent during that run;
    # if the budget is over its limit after a run, raise BudgetExceeded (a run that ran out of money isn't a trial);
    # out_dir: truncate trials.jsonl at start, append per trial; write
    # transcripts/<task>__<arch with ":" and "@" -> "_">__<k>.json
def summarize(trials) -> dict[arch, {n, accuracy, errors, provider_errors, tokens (mean in+out), peak_context (max),
                                     cost (mean), p50_s, agents, calls, missing (runs with any), conflicts (sum),
                                     tokens_by_role (mean per task), by_task {task_id: "passes/trials"}}]
    # provider-error trials excluded from everything except the provider_errors count
def render(trials, baseline=None) -> str   # table: accuracy, errors "(+provider)", tokens/task, × tokens vs
    # baseline (default: the first arch) formatted like "1.0×", peak prompt, $/task, p50 s, agents, calls, runs w/ missing shards, conflicts;
    # then a task × arch verdict table; then tokens by role for archs with more than one role
```

## 6. CLI: `python -m agentlab.multi`
```
tasks                                                  print each question and its gold answer (free)
run    --archs single:mid,orch:mid:fast,mapreduce:fast:mid [--tasks id,id] [--trials 1] [--budget 1] [--max-parallel 6]
report RUN_DIR [RUN_DIR ...] [--baseline ARCH] [--a ARCH --b ARCH]   merge the dirs' trials; render + optional
                                                       paired comparison (Node 04 compare)
show   RUN_DIR --task ID --arch ARCH [--trial 0] [--agent PREFIX]   print transcripts (2,000 chars per message)
```
`run` and `tasks` seed a fresh database in `new_run_dir(RUNS / "multi")`; import both at module level
(`from agentlab.config import RUNS, new_run_dir`: the tests monkeypatch the module's `RUNS`). `run` validates every
architecture and resolves every alias (`config.resolve`) before seeding or spending; rejects unknown task ids;
writes `meta.json`, `trials.jsonl`, `transcripts/`, `report.md`; on `BudgetExceeded` reports the completed trials;
prints each non-passing trial's grade detail.

## Done when
`make grade N=10` passes except `test_reconcile.py` (the learner's). Explain your diff: how a worker's context is
isolated, where parallelism happens, and what the lead sees after a delegation.
