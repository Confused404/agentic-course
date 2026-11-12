# Ticket FIN-15: "Support costs too much per resolved ticket, and it's slow"

| | |
|---|---|
| **Estimate** | 1.5 days |
| **Cost cap** | ≈ $1–2 for the default bench (28 tasks × 5 configurations, one trial; the `mid` configurations are most of it; the default `--budget` is $3); ≈ $0.10 for the cache experiment on `fast`. Tasks 2, 3 and 8 are free. Free models: $0 but ≈ 600 requests for the default bench (the 1,000/day tier; or `--suite` the regression file alone, ≈ 250); costs are then *shadow-priced* as the paid models the aliases stand for, and the cache experiment needs a paid model (free providers rarely report cache hits) |
| **Prerequisites** | Node 01 (latency and caching experiments), Node 04 (evals), Node 05 (variants), Node 09 (routing), Node 14 (wrappers around models) |
| **You will touch** | `agentlab/perf/{prefix.py,economics.py}` (yours); caching layouts, the cascade, the bench and the CLI (agent); `docs/adr/0012-*` |
| **Done when** | `make grade N=15` green · cache experiment explained call by call · a configuration chosen from the bench with its cost per *resolution*, not per call · ADR 0012 |

## Story
Finance sent a one-line email: "Support AI: $0.031 per conversation last month, up 40%. Why, and can it be half?"
Support sent another: "Customers say it's slow." Both are right, and both are asking the wrong question. What the
business pays for is a *resolved* conversation: a cheap model that fails more often hands more customers to a
person, and a person costs dollars, not fractions of a cent. Your job: measure where the money and the seconds go,
cut both with caching and routing, and prove you didn't buy savings with resolutions.

## Deliverables
1. `prefix.py::first_divergence` and `economics.py` (`percentile`, `unit_economics`): **by hand** (AGENT-OFF). The
   first is how you debug a prompt cache; the second is the number you'll defend to finance.
2. Cache layouts, the cache doctor, the cascade, the bench and the CLI: coding agent, from `SPEC.md`.
3. The cache experiment: four layouts, every miss explained.
4. The bench table with your chosen configuration, and why.
5. `docs/adr/0012-cost-and-latency.md`.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + predictions | 1.5h | |
| prefix.py + economics.py | 1.5h | `git show solution/node-15:agentlab/perf/prefix.py` |
| Agent builds SPEC + review | 2h | `make solution N=15` |
| Cache experiment | 1h | 6 tasks |
| Bench + cascade tuning | 2h | the regression suite only |
| Latency breakdown + self-hosting math | 45m | |
| ADR | 30m | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Caching | "turned it on" | hit rate measured | + every miss explained from the requests, the layout fixed, the write premium accounted for |
| Routing | one model for everything | a cascade measured | + escalation reasons, wasted spend and cold caches counted; a signal that misses bad cheap answers named |
| Economics | $/call | $/conversation | + $/resolution and blended cost with a defended human-cost figure; noise acknowledged |
| Latency | one average | p50 and p95 | + where the time goes (turns × per-call time), and which lever moves the tail |
