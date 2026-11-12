# Ticket DEV-03: Build `shopdev`, a coding agent, and let it fix Shopfront's bugs

| | |
|---|---|
| **Estimate** | 3 days |
| **Cost cap** | ≈ $5 (several shopdev runs on a mid-size model at ~$1 each, plus a vendor comparison; Claude Code/OpenCode comparison billed separately) · Free models: $0 but ≈ 300 requests (a shopdev run is 30–60 calls); use the 1,000/day tier or spread runs over days. In free mode `mid` is the same free model as `fast`: the vendor comparison is `fast` vs `gpt-fast`/`local` |
| **Prerequisites** | Node 02 (your loop and the tool registry) |
| **You will touch** | `agentlab/shopdev/edit.py` + `permissions.py` (yours), the rest of `agentlab/shopdev/` (agent), `docs/threat-models/shopdev.md` |
| **Done when** | `make grade N=03` green, **including `test_seeded_bugs.py`, fixed by shopdev**, threat model written, diff reviewed |

## Story
Shopfront has bugs: discount codes stack when they shouldn't, the revenue report drops the last day, search
skips the first page. The founder asks whether an AI could fix them. You could ask Claude Code, but you want to
understand what's inside such a tool and what it can do to your machine. So you build one: `shopdev`. It
works in an isolated git worktree, runs commands in a sandbox with no network, and every tool call passes a
permission gate *you* wrote. Then you point it at the bugs and review its diff like any colleague's.

## Learning objectives
See TEXTBOOK: edit-tool design, the verification loop and how it's gamed, the lethal trifecta, permission gates,
sandbox levels, workspace isolation.

## Deliverables
1. `agentlab/shopdev/edit.py::edit_file`: **by hand** (AGENT-OFF).
2. `agentlab/shopdev/permissions.py::PermissionGate.decide`: **by hand** (AGENT-OFF).
3. The rest of shopdev (file tools, sandbox, worktrees, gated executor, CLI, Docker image): coding agent, from `SPEC.md`.
4. `docs/threat-models/shopdev.md`: your threat model.
5. The seeded bugs **fixed by shopdev runs** (merged from its worktree branch into yours), with run logs.
6. A comparison note: the same bug given to Claude Code or OpenCode.

## Time boxes
| Step | Box | Escape hatch |
|---|---|---|
| TEXTBOOK + self-check | 2h | |
| `edit_file` by hand | 1.5h | **study only**: `git show solution/node-03:agentlab/shopdev/edit.py`, then rewrite from memory (`make solution` would also merge the bug fixes and spoil step 6) |
| `PermissionGate` by hand | 2.5h | same, with `agentlab/shopdev/permissions.py` |
| Threat model | 1h | |
| Agent builds SPEC + review | 3h | `make solution N=03` (only once you're past step 6, or you lose the bug-fixing exercise) |
| shopdev runs on the 3 bug areas + diff review | 4h | fix with Claude Code and study why shopdev failed |
| Red-team + comparison | 2h | |

## Rubric (0–2 each)
| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Edit tool | tests red | green | green, and you can say why each error message is worded the way it is |
| Gate | tests red | green | green, plus ≥ 5 extra adversarial cases you found and handled (in your own scratch test) |
| Threat model | missing | lists the trifecta | maps every channel to a mitigation *and* states residual risk honestly (e.g. LocalSandbox) |
| Bug fixes | not fixed | fixed by shopdev | fixed, diff reviewed, and one fix you rejected or improved, with the reason |
| Comparison | none | anecdote | same bug, two agents, turns/cost/diff quality compared |
