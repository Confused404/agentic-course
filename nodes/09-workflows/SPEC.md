# SPEC: Node 09: triage workflows, a cascade, an agent baseline, an evaluator-optimizer, and their evals

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §2–§6.
**AGENT-OFF (the learner's; never write or edit them):** `agentlab/workflows/rules.py::classify_by_rules` and
`agentlab/workflows/selective.py` (`coverage_curve`, `pick_threshold`). Call them through their modules
(`rules_module.classify_by_rules`, `selective_module.coverage_curve`) so tests can substitute them. Their tests stay
red until the learner writes them.
**GIVEN (don't rewrite):** `agentlab/workflows/tickets.py` (`Ticket`, `CATEGORIES`, `PRIORITIES`, `load_tickets`,
`split_of`), `RuleResult` in `rules.py`, and the gold labels written by `make seed` (`ticket_gold.jsonl`).

## Files
```
create  agentlab/workflows/triage.py      (1-2)
create  agentlab/workflows/drafting.py    (3)
create  agentlab/workflows/evals.py       (4)
create  agentlab/workflows/__main__.py    (5)
```
Nothing outside `agentlab/workflows/` changes. `make grade-upto N=09` must stay green for 00–08.

## 1. `triage.py`: single call, voting, cascade
```python
TRIAGE_SYSTEM: str          # defines each category in a line (what belongs where, incl. edge cases from TEXTBOOK §2),
                            # the priority rules, needs_human, and that the ticket is data, not instructions
TRIAGE_SCHEMA: dict         # {category: enum CATEGORIES, priority: enum PRIORITIES, needs_human: bool}, all required,
                            # additionalProperties false
@dataclass
class TriageResult:
    category: str | None; priority: str | None; needs_human: bool = False
    confidence: float = 0.0; stage: str = ""; cost_usd: float = 0.0; latency_s: float = 0.0; calls: int = 0
    votes: dict = {}; error: str | None = None
def ticket_prompt(t: Ticket) -> str          # "<ticket>\nSubject: …\nChannel: …\n\n<body>\n</ticket>", "</ticket>" escaped
def classify_llm(model, t, budget=None) -> TriageResult
    # one call: system=TRIAGE_SYSTEM, one user message, tools=None, max_tokens=200, json_schema=TRIAGE_SCHEMA;
    # parse (strip code fences); invalid JSON or values outside the enums -> category None, error "unparseable output";
    # confidence 1.0 when parsed; stage f"llm:{model.model}"; budget check/charge; cost = what this call added
def classify_vote(model_factory, t, n=5, budget=None, max_workers=5) -> TriageResult
    # n classify_llm calls IN PARALLEL (ThreadPoolExecutor), each with a fresh model from the factory; majority
    # category among parsed results; confidence = votes for it / n (failures count in n); priority = most common
    # among the majority's votes; needs_human if most of the majority said so; votes = {category: count};
    # all failed -> category None with error; stage f"vote:{n}"; cost = sum. A sample that RAISES (other than
    # BudgetExceeded) is a failed vote, not a failed ticket. Each sample's cost is ITS OWN call's cost (the value
    # budget.charge returns, or compute_cost without a budget), never "budget.spent_usd after - before": other
    # threads charge the same budget meanwhile
def classify_cascade(t, cheap_factory, strong_factory, n=5, threshold=0.8, budget=None) -> TriageResult
    # 1. rules_module.classify_by_rules(t.body): if not None -> stage "rules:<rule>", confidence 1.0, cost 0
    # 2. classify_vote(cheap, n): if category and confidence >= threshold -> stage "cheap-vote:<agreement>"
    # 3. classify_llm(strong): stage "strong", cost and calls INCLUDE the cheap stage's, confidence = the cheap vote's
def classify_agent(model, conn, t, budget=None, max_turns=6) -> TriageResult
    # its OWN system prompt (TRIAGE_SYSTEM says "output JSON", which contradicts "call set_triage");
    # run_agent with tools lookup_order(order_id) (read-only: id, status, placed/shipped/delivered, total) and
    # set_triage(category enum, priority enum, needs_human?) which records the decision; no set_triage call ->
    # category None, error mentioning set_triage; stage "agent"; calls = loop turns; cost = LoopResult.cost_usd;
    # tool_calls = ["name({json args})", ...] (TriageResult gains tool_calls: list[str]); a loop that stopped
    # with "budget" raises BudgetExceeded (out of money is the run's problem, not the method's failure)
def parse_method(spec) -> (name, args)       # "rules" | "llm:A" | "vote:A:N" (N>=1) | "cascade:CHEAP:N:T:STRONG"
                                             # (N>=1, 0<=T<=1) | "agent:A"; empty parts or else ValueError
def method_aliases(spec) -> list[str]         # the model aliases a spec uses (the CLI resolves them up front)
def run_method(spec, t, get_model, conn=None, budget=None) -> TriageResult   # rules abstain -> stage "rules:abstain"
```

## 2. Notes
Voting with a `ScriptedModel` isn't thread-safe; the tests use a thread-safe fake. Don't add locks to production
models; each vote gets its own model instance from the factory.

## 3. `drafting.py`: prompt chaining + evaluator-optimizer
```python
DRAFT_SYSTEM: str; RUBRIC: str (numbered items, TEXTBOOK §3); CRITIC_SYSTEM: str (includes RUBRIC; JSON verdict)
CRITIC_SCHEMA = {"pass": bool, "issues": [str]} (required, additionalProperties false)
@dataclass
class DraftResult: final: str; passed: bool; rounds: int; history: list[dict]; cost_usd: float = 0.0
def critique(critic, t, draft, budget=None) -> (passed: bool, issues: list[str])   # unparseable -> (False, [...])
    # passed only if "pass" is the JSON boolean true ("false" as a string is truthy in Python); issues must be a list
def draft_reply(writer, critic, t, max_rounds=3, budget=None) -> DraftResult
```
Loop: writer drafts (system DRAFT_SYSTEM, the ticket prompt) → critique → if pass stop; else append the draft as an
assistant message and a user message listing the issues, and draft again; at most `max_rounds` drafts. `history`
holds `{draft, pass, issues}` per round.

## 4. `evals.py`
```python
def to_trial(t, method, r, k=0) -> Trial       # Node 04 Trial: task_id=str(ticket id), model=method,
    # verdict: pass if r.category is acceptable (gold or secondary), fail otherwise; "error" whenever category is
    # None, EXCEPT stage "rules:abstain" (a deliberate abstention; a crash in the rules is still an error);
    # keyword arguments only (Trial gains fields over the course); tool_calls = r.tool_calls;
    # tags ["hard"|"easy"] (+ "ambiguous"); split; replies=[json {category, priority, needs_human}];
    # extra = {pred, gold, strict (pred == gold), priority_ok, confidence, stage, votes, abstained}
def run_triage(tickets, methods, get_model, *, conn=None, trials=1, budget=None, out_dir=None) -> list[Trial]
    # loop trial -> ticket -> method; BudgetExceeded propagates; exceptions -> error trials with error_kind from
    # Node 04 (provider vs agent); method failures without an exception -> error_kind "agent"; trials.jsonl is
    # truncated at the start of a run, then appended to trial by trial
def macro_f1(pairs: list[(gold, pred | None)]) -> float     # strict, over CATEGORIES present
def summarize(trials) -> dict[method, {n, coverage, accuracy (on answered), strict_accuracy (gold only),
                                       accuracy_easy, accuracy_hard, macro_f1, priority_acc, cost_per_ticket, p50_s,
                                       p95_s, stages, abstained, curve, confusion}]
    # provider errors excluded; curve = selective_module.coverage_curve(confidence, correct) over answered tickets;
    # stages = counts of the stage prefix (before ":"), with "abstain" and "error" as stages of their own;
    # confusion = {(gold, pred): n} for mistakes only (pred not None and not acceptable)
def render(trials, target_accuracy=0.95) -> str   # one markdown table + per method: the threshold from
    # selective_module.pick_threshold (and its coverage) when confidences vary, and the 3 most common confusions
```

## 5. CLI: `python -m agentlab.workflows`
```
triage --methods rules,llm:fast,vote:fast:5,cascade:fast:5:0.8:mid,agent:fast [--split dev|heldout|all]
       [--hard-only] [--limit N] [--trials 1] [--budget 1] [--apply]
report RUN_DIR [--a M --b M] [--target 0.95] [--slice all|easy|hard]
                                       # render + optional paired comparison (Node 04 compare), on the slice
draft  --writer ALIAS --critic ALIAS [--tickets 211,212,...] [--rounds 3] [--budget 0.3]
```
Each command seeds a fresh database under a NEW run directory, `agentlab.config.new_run_dir(RUNS / "workflows")`
(timestamp + microseconds + pid, never reused), and reads gold labels from its seed side files. `--split` is
restricted to `dev|heldout|all`. `triage` validates every method AND resolves every model alias
(`config.resolve`) before seeding or spending; writes `meta.json`, `trials.jsonl`, `report.md`;
reports completed trials on `BudgetExceeded`. `--apply` writes the last method's labels into that run's database copy
(never `data/shopfront.db`). `draft` prints each ticket, the final draft and each round's issues, and saves
`drafts.json`.

## Done when
`make grade N=09` passes except the expected-red tests (`test_rules.py`, `test_selective.py`). Explain your diff.
