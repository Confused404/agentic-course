# Node 03 cheat sheet: coding agents

**Harness** = loop + file tools + shell + permission gate + sandbox + workspace (worktree) + verification (tests).
Output is a **diff** for review, not a claim.

**Edit tool**: exact, unique `old_str` → `new_str`; loud errors (not found + whitespace hint; N matches + lines);
atomic write; return a numbered snippet. Read before edit. Line-numbered paginated reads; grep before read.
Truncate shell output head+tail.

**Agents game checks**: edit tests, special-case inputs, detect pytest, claim success → protect tests (gate + CI),
held-out checks, read the diff, separate evaluator (Node 12).

**Lethal trifecta**: private data + untrusted content + exfiltration channel → injection can steal. Remove a leg.
Coding agent: `.env`/DB/code · files/deps/DB text/issues · network/git push/published files/URLs. Also destruction
and persistence (hooks, CI, profiles).

**Gate**: allow (no effects or reviewable via git) · ask (unknown) · deny (exfil, destruction, secrets, outside paths,
protected files). Deny wins. Split compound commands; every segment must be allowed; substitution, interpreters
(`python -c`, `bash -c`), redirection, env assignment → ask. Canonicalise paths (resolve symlinks, `..`, `~`).
Fail closed. Beware approval fatigue.

**Sandbox levels**: none · process limits + scrubbed env (not a boundary) · container (`--network none`, `--cap-drop
ALL`, no-new-privileges, non-root, only the workspace mounted) · microVM · remote ephemeral. `--network none` is the
single most valuable flag.

**Evaluate**: hidden/held-out tests, pass rate, cost and turns per fix, diff review.
