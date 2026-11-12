# Ticket SETUP-00: Get Shopfront running and talk to three model providers

| | |
|---|---|
| **Estimate** | half a day |
| **Cost cap** | $0.05 (`hello_providers.py` has its own Budget) · Free models: $0, ≈ 6 requests (`hello_providers.py` and `make check-env`'s live test) |
| **You will touch** | `.env`, `LEARNING_LOG.md`; no code yet |
| **Done when** | `make grade N=00` green · `hello_providers.py` works on ≥ 2 models from different vendors · you've read a trace |

## Story
You've just joined Shopfront, a small home-and-outdoor store, as its first "AI engineer". The
founder wants a support assistant, an internal coding agent, and eventually an ops agent that
runs overnight. The codebase is small but the data is real-world messy. Before you build
anything, get the app running, get access to models from more than one vendor, and learn to
see what a model call actually costs and does.

## Learning objectives
1. Set up a reproducible environment and explain why each piece (pinned versions, seeded data,
   fixed clock, budgets, traces) matters for *agent* work specifically.
2. Call models from three vendors through their raw SDKs and name concrete differences in what comes back
   (with an Anthropic key you also see a second wire format; Node 01 shows both either way).
3. Read a trace and a cost ledger.

---

## Step 1: Tools (30 min)
Install, if missing:
- **uv** (Python package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Ollama** is **not** needed. `local` means "an open-weights model from a third vendor", and by default it's a
  free one hosted on OpenRouter. If you have 16 GB+ of RAM and want a model on your own machine, install Ollama,
  `ollama pull qwen3:8b` (~5 GB) and put `AGENTLAB_ALIAS_LOCAL=ollama:qwen3:8b` in `.env`.
- **Docker** (Node 03 sandbox). Docker Desktop, OrbStack or Colima all work.
- **Claude Code** and/or **OpenCode**: your coding agents. Both read `AGENTS.md` at the repo
  root (Claude Code via `CLAUDE.md`, which imports it).

## Step 2: Repo and keys (20 min)
```bash
make setup        # creates .venv, installs pinned deps, seeds data/shopfront.db, copies .env
```
**One key is enough.** Create an **OpenRouter** key (openrouter.ai → Keys), put it in `.env` as
`OPENROUTER_API_KEY`, and you're done: with no other key, every model alias points at a **free** OpenRouter model
(three vendors, $0). Then:
```bash
make check-env    # which model each alias means now, free or paid, your free allowance, and a live test call
make models       # are the model ids in config/models.toml real today? (free models rotate)
```
What free costs you instead of money (shown by `make check-env`):
- **Rate limits**: 20 requests a minute (the course paces itself to stay under it) and **50 requests a day**, or
  **1,000 a day once you've bought $10 of credits** in total. Most nodes' eval runs need a few hundred requests;
  each README's "Cost cap" row says how many. With 50 a day you can follow every node, slowly; $10 of credits,
  bought once, makes the free tier practical.
- **Quality**: free models are capable but not frontier models, and `mid`/`top` are the same free model in free
  mode. Where a node's lesson is a comparison with a stronger model, it says so.
- **Churn**: free models come and go without notice. If `make models` shows a ✘, swap the id in
  `config/models.toml` (`[aliases_free]`) or override one alias in `.env`, e.g. `AGENTLAB_ALIAS_FAST=...`.
  OpenRouter also falls back to the next free model on errors (`[fallbacks]`), so a single outage won't stop you.
- **Privacy**: some free providers log prompts; allow that in OpenRouter's privacy settings if a call is
  refused. The course data is synthetic.

Want paid models later? Either add `ANTHROPIC_API_KEY` (Claude direct; `fast`/`mid`/`top` become Claude, the rest
stays on OpenRouter), or buy OpenRouter credits and set `COURSE_MODELS=openrouter` (everything through one key).
`config/models.toml` explains the three modes. **Set a spending limit** wherever you add money: the Anthropic
console's monthly limit, or a credit limit on the OpenRouter key.

> **Why two layers of spending limits?** `COURSE_BUDGET_USD` caps one process, so a runaway
> loop dies quickly. The provider dashboard limit caps the month, in case you, a script or a
> coding agent bypasses the course code. Defense in depth is a theme of this course.

## Step 3: Explore Shopfront (30 min)
```bash
make check        # Shopfront's tests: green
make run          # http://localhost:8000; the assistant panel says "not built yet"
```
Try the search box: type `tent`, then `Tent`, and page through results. **Search is deliberately
broken.** It has seeded bugs your coding agent will fix in Node 03. Log two symptoms you notice in
`LEARNING_LOG.md`.

Read, in this order:
1. `shopfront/FIXTURES.md`: the named customers and orders every eval uses. Memorize order **4821**.
2. `shopfront/services.py`: the business logic agents will call. Notice where policy is enforced.
3. `data/help_center/refund-policy.md` and `returns-policy-2025.md`. Notice that they contradict each other.
4. `agentlab/llm/types.py`: the provider-neutral contract you will implement in Node 02.

## Step 4: Hello, three vendors (30 min)
```bash
.venv/bin/python nodes/00-setup/hello_providers.py
make trace
```
Read the script first. It prints each vendor's raw `usage` object as well as the normalized numbers.
Then answer in `LEARNING_LOG.md` (first entry):
- Where does the system prompt go in each SDK?
- What are the usage fields called in each? Which one reported cost directly?
- Which was fastest? Was that the model, the provider, or the network? (`make check-env` showed the same.)

## Step 5 (optional): A trace UI (20 min)
The JSONL traces + `make trace` are enough for the whole course. If you want a UI:
```bash
docker run -d -p 6006:6006 --name phoenix arizephoenix/phoenix:latest
echo 'OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006' >> .env   # base URL: the exporter appends /v1/traces
```
Re-run `hello_providers.py` and open http://localhost:6006. Langfuse and Jaeger also accept
OTLP. Point the same variable at them.

## Step 6: Wire up your coding agents (20 min)
- **Claude Code**: run `claude` in the repo root. Ask it: *"Summarize AGENTS.md and list which
  files you're not allowed to modify."* If the answer is right, the rules file is loaded.
- **OpenCode**: run `opencode` in the repo root, authenticate providers with `opencode auth login`,
  and ask the same question. OpenCode can use OpenRouter's free models too (`opencode auth login` → OpenRouter),
  or Ollama if you installed it (see `APPENDIX-2026-11.md`).

Throughout the course, try each ticket's SPEC with **both** agents at least once. In Node 12 you'll
compare them properly.

Optional but recommended: [`docs/agent-permissions.md`](../../docs/agent-permissions.md) shows how to make
each agent's *own* permission system refuse edits to tests and data, so AGENTS.md is enforced rather
than just requested.

## Done when
- [ ] `make grade N=00` is green
- [ ] `hello_providers.py` succeeded on at least two models from different vendors
- [ ] `LEARNING_LOG.md` has your first entry (the three questions above)
- [ ] Both coding agents correctly recite the AGENTS.md rules
- [ ] Two search-bug symptoms logged

## When versions drift
Everything is pinned in `pyproject.toml` as of 2026-11-04. If, months from now, an install fails or an
SDK call errors:
1. Keep the pins and use `uv` with Python 3.12. Pinned versions keep working long after release.
2. If a *provider* changed its API (e.g. a model ID retired), the fix is in `config/models.toml`, not code.
3. Each node's `APPENDIX-*.md` lists the version-specific facts that node relies on, so you know exactly
   what to re-check.

## Socratic review
Paste into your coding agent after finishing:
> I just finished Node 00 of an agentic engineering course (read nodes/00-setup/README.md and
> shopfront/FIXTURES.md). Don't write code. Ask me 5 questions, one at a time, that test whether I
> understand why this setup uses a fixed clock, a deterministic seed, per-process budgets and
> traces. After each answer, tell me what I got right and what I missed.
