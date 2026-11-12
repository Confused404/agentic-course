# Node 00 cheat sheet

```bash
make setup / check-env / models / seed / run / check
make grade N=NN            # offline grader (free)
make eval N=NN BUDGET=2    # live evals (capped; Nodes 02 and 04)
make trace [ARGS=--full]   # latest trace as a tree
make new-ticket N=NN       # branch node-NN-<you>
make solution N=NN         # escape hatch
```

| Thing | Where |
|---|---|
| Model aliases & prices | `config/models.toml` |
| Per-process spending cap | `COURSE_BUDGET_USD` in `.env` (default $1) |
| Traces | `runs/traces/*.jsonl` |
| Cost ledger | `runs/costs.jsonl` |
| "Today" | 2026-11-01 12:00 UTC (`SHOPFRONT_NOW` to override) |
| Fixtures | `shopfront/FIXTURES.md` (order 4821 = the classic trap) |
| Provider-neutral types | `agentlab/llm/types.py` |
| Rules for coding agents | `AGENTS.md` (CLAUDE.md imports it) |

**Raw SDK differences you saw today**
| | Anthropic Messages | OpenAI-compatible Chat |
|---|---|---|
| System prompt | top-level `system=` | first message, role `system` |
| Response text | `resp.content[*].text` (blocks) | `resp.choices[0].message.content` |
| Stop reason | `stop_reason`: end_turn / tool_use / max_tokens | `finish_reason`: stop / tool_calls / length |
| Usage | `input_tokens`, `output_tokens`, `cache_*_input_tokens` | `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens` |
| Sampling knobs | effort, thinking (no temperature on current models) | temperature, top_p, seed, reasoning_effort |
