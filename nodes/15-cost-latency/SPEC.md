# SPEC: Node 15: cache layouts, a cache doctor, a cascade, and a cost/latency bench

**For the coding agent.** Read `AGENTS.md`. Background: TEXTBOOK §1–§5.
**AGENT-OFF (the learner's; never write or edit them):** `agentlab/perf/prefix.py::first_divergence` and
`agentlab/perf/economics.py` (`percentile`, `unit_economics`). Call them through their modules
(`prefix_module.first_divergence`, `economics_module.unit_economics`) so tests can substitute them.
**GIVEN (don't rewrite):** `agentlab/perf/recorder.py` (`RecordingModel(inner, sink, label=...)`, `request_dict`;
records carry `label`, `answered_by`, `wait_s`), `pricing.py` (`usage_from`, `list_price`, `call_cost`, `is_priced`,
`cache_read_share`), the `Divergence`/`Economics` dataclasses. Reuse Node
04's `run_trial`/`Trial`/`load_tasks`/`load_trials`, Node 05's `get_prompt("v2")` and tool variant `"v2"`, Node 02's
`Budget`.

## Files
```
create  agentlab/perf/caching.py     (1)
create  agentlab/perf/router.py      (2)
create  agentlab/perf/bench.py       (3)
create  agentlab/perf/__main__.py    (4)
```
Nothing outside `agentlab/perf/` changes. `make grade-upto N=15` must stay green for 00–14.

## 1. `caching.py`
```python
POLICIES = ("off", "auto", "explicit", "timestamp")
class CachePolicyModel:            # (inner, policy, *, now=None -> datetime.now(UTC)); unknown policy -> ValueError
    # forwards unknown attributes to inner (provider, model, ...)
    def complete(*, system, messages, tools=None, max_tokens=1024, **opts):
        # drop any "cache" opt the caller passed, then:
        # off: nothing more · auto: opts["cache"]=True · explicit: auto + system -> [TextBlock(<system text>,
        # cache=True)] · timestamp: auto + system -> f"Current time: {now().isoformat(timespec='seconds')}\n\n"
        # + <system text>  (the anti-pattern, for the experiment). A list-of-TextBlock system becomes its text
        # joined with "\n\n".
def min_cacheable(record) -> int     # 512 for Anthropic/Claude models, else 1024 (rough; per provider docs)
def diagnose(records, *, min_cacheable_tokens=None, ttl_s=300.0) -> list[dict]
    # records of ONE conversation, in order. Compare each call with the previous call TO THE SAME MODEL (caches
    # are per model; skip records without usage as "previous"). Row: {seq, model, prompt_tokens (usage
    # total_input), cache_read_tokens, cache_write_tokens, read_share (pricing.cache_read_share; None without
    # usage), section ("first" for a model's first call, else Divergence.section or "extends"),
    # shared_tokens_est, why}. why: first call -> "nothing to reuse yet" (+ "it wrote the cache" only if
    # cache_write_tokens > 0); else Divergence.detail, plus a note when shared tokens < the minimum
    # (min_cacheable_tokens or min_cacheable(record)); and when shared tokens reach the minimum but < 5% was read,
    # "BUT nothing was read: " + the applicable causes: caching not requested (no opts["cache"] and no cache
    # marker on a system block), opts changed from the previous call, t_start gap > ttl_s, a different
    # answered_by, and always "routed to a different upstream server/provider, or no cache entry was written".
def cache_summary(conversations: list[list[dict]]) -> dict
    # {calls, prompt_tokens, cache_read_tokens, cache_write_tokens, read_share (read/prompt or None),
    #  divergences: {section: count}} over every diagnose() row
```

## 2. `router.py`
```python
HIGH_STAKES = frozenset({"issue_refund", "cancel_order"})
@dataclass class CascadeModel:     # a ChatModel
    cheap; strong; budget=None; high_stakes=HIGH_STAKES; error_lookback=2; sticky=True
    calls=0; escalations=0; wasted_usd=0.0; reasons: list[str]
    # provider/model start as cheap's; after every call they are the ANSWERING model's (the loop prices with them)
    def pre_reason(messages) -> str | None      # INPUT-only: "recent tool error" if any of the last error_lookback
        # ToolResultBlocks of the CURRENT customer turn (user messages after the last one with non-result content)
        # is_error; else None
    def reason(resp, messages=None) -> str | None   # OUTPUT signals, first that applies: "high-stakes tool:
        # <sorted names>" · "unparseable tool arguments" · "empty answer" (end_turn, no text, no calls) · else None
    def complete(*, messages, **kw):
        # sticky and already escalated -> strong only. pre_reason -> escalate straight to strong (no cheap call).
        # Else budget.check(); cheap.complete; reason None -> return it. Else charge the discarded cheap response
        # to the budget (budget.charge(cheap.model, usage, provider=cheap.provider); add to wasted_usd).
        # Escalating: escalations += 1, append the reason, remember stickiness, return strong.complete(same args).
```

## 3. `bench.py`
```python
EFFORTS = ("low", "medium", "high")
@dataclass(frozen=True) class BenchConfig: spec; cheap; strong=None; cache="off"; effort=None; sticky=True
    aliases -> [cheap] (+ [strong])
def parse_config(spec) -> BenchConfig
    # "MODEL[+OPTION...]"; MODEL = alias or "CHEAP>STRONG" (aliases only: ":", " " or "," in it -> ValueError;
    # an empty side or two ">" -> ValueError); OPTIONS: cache:<POLICIES>, effort:<EFFORTS>, nosticky (cascades
    # only); anything else -> ValueError naming the allowed options
def build_model(cfg, get_model, sink, budget) -> (model, cascade|None)
    # leaf(alias) = CachePolicyModel(RecordingModel(get_model(alias), sink, label=alias), cfg.cache): recording
    # is INSIDE the cascade, so a discarded cheap answer is still recorded. Cascade -> CascadeModel(leaf(cheap),
    # leaf(strong), budget=budget, sticky=cfg.sticky)
def assistant_opts(cfg) -> {"system_prompt": get_prompt("v2"), "tool_variant": "v2",
                            "model_opts": {"effort": e} if cfg.effort else {}}
def run_bench(tasks, configs, *, template_db, get_model, trials=1, budget=None, judge_factory=None,
              sim_factory=None, price_as: dict[alias, model_id] | None = None, out_dir=None) -> list[Trial]
    # parse all configs first (duplicates -> ValueError). Loop trial -> task -> config (interleaved), fresh sink and
    # model per trial, Node 04 run_trial(model_label=config spec, assistant_opts(cfg)). Put in trial.extra:
    # calls (the records), recorded_cost (sum call_cost(r)), shadow_cost (sum call_cost(r, price_as.get(r["label"]))
    # if price_as else None), price_as, escalations, escalation_reasons. out_dir -> trials.jsonl (truncated at
    # start, one json.dumps(asdict(trial), default=str) line per trial). BudgetExceeded from run_trial propagates
    # (the trial that crossed the cap is lost; the CLI reports that spend).
@dataclass class ConfigSummary: config; economics (asdict of Economics); shadow (all trials have shadow_cost);
    calls_per_conversation; prompt_tokens_per_conversation; cache (cache_summary); escalation_rate (escalations
    per conversation; None for non-cascades); escalation_reasons {reason prefix before ":": count};
    unpriced_calls (records is_priced() says have no real price, using the trial's price_as when shadow);
    call_latency_p50/p95 (per recorded call with usage, latency_s - wait_s, via economics.percentile);
    wait_s_per_conversation
def summarize(trials, *, human_cost_usd) -> {config: ConfigSummary}
    # economics_module.unit_economics(trials, human_cost_usd=..., costs=shadow costs if shadow else
    # recorded_cost (falling back to trial.cost_usd))
def pareto(summaries) -> list[str]      # not dominated on (resolution_rate higher, blended_cost lower); n == 0 out
def render(summaries, *, human_cost_usd) -> str
    # markdown: config, n, resolved %, $/conversation, $/resolution (∞ shown as "∞"), blended $, p50 s, p95 s,
    # calls, prompt tok, cache read %, escalations, Pareto ★; then notes: blended $ defined; per-call latency
    # p50/p95 per config; pacing waits when > 0.5 s per conversation; unpriced call counts ("UNPRICED"); and, if
    # any summary is shadow-priced, a line starting "Costs are SHADOW prices"
```

## 4. `__main__.py`
```
python -m agentlab.perf bench [--configs C1,C2,...] [--suite PATHS] [--tags T] [--trials 1] [--budget 2.0]
                              [--price-as auto|none|ALIAS=MODEL_ID,...] [--human-cost 4.0]
python -m agentlab.perf report RUN_DIR [--human-cost 4.0]
python -m agentlab.perf doctor RUN_DIR [--config SPEC] [--task ID]
python -m agentlab.perf breakeven --gpu-usd-per-hour X --tokens-per-second Y [--utilization 0.3] [--api-usd-per-mtok Z]
```
- `bench`: default configs `mid,fast,fast>mid,mid+cache:auto,fast>mid+cache:auto`; in free mode
  (`config.models_mode() == "free"`, where fast and mid are the same model but shadow-priced differently)
  `mid,fast,fast>mid,fast+cache:auto,fast+cache:timestamp`. Default `--budget 3.0`. Default suite: Node 04's
  `regression.yaml,capability.yaml` (paths relative to the repo root). Validate **before** creating anything:
  every config (parse_config), every alias (`config.resolve`), trials >= 1, budget > 0, human cost >= 0, price-as.
  `--price-as auto` = in free mode, each alias priced as its `[aliases]` (paid) target's model id; otherwise none.
  An explicit `ALIAS=MODEL_ID,...` must name only aliases the configs use, cover all of them, and use model ids
  `price_for` knows (else ValueError).
  Out dir `new_run_dir(RUNS / "perf")`, a seeded template DB in it, `meta.json` (configs, resolved aliases, mode,
  price_as, trials, task ids). Judge and simulator from `[evals]` in `config/models.toml`. On an exception mid-run,
  report the trials already written; if the budget spent exceeds the written trials' cost + overhead, add a line
  saying how much spend isn't in the table. Write and print `report.md`.
- `report`: re-render a run dir. `doctor`: for each trial (filtered by --config/--task; at most 5 unfiltered),
  one line per call: seq, model, prompt tokens, cache read %, why.
- `breakeven`: `selfhost_breakeven(gpu_usd_per_hour, tokens_per_second, utilization, api_usd_per_mtok=None)` ->
  {selfhost_usd_per_mtok = gpu / (tps × 3600 × utilization) × 1e6, breakeven_utilization (only with an API price)
  = gpu / (tps × 3600) × 1e6 / api}; gpu < 0, tps <= 0 or utilization outside (0, 1] -> ValueError. Print both,
  noting when break-even utilization is above 100%.

## Tests
`nodes/15-cost-latency/tests/`: graders for the two AGENT-OFF files (`test_prefix.py`, `test_economics.py`) and
offline tests of the layouts, the doctor, the cascade, the bench (a polite fake model through two Node 04 tasks)
and the CLI. The `needs_prefix`/`needs_economics` fixtures skip dependent tests until the AGENT-OFF code exists.
