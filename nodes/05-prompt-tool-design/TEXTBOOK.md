# Node 05 Textbook: Prompt and tool design, measured

> A prompt is a program whose interpreter is a model; a tool definition is an API whose only client is a model.
> Both deserve the same care as code, and like code they're only as good as the tests that check them. This node
> teaches what makes system prompts, tool descriptions, return values and error messages work, and how to
> change them **one measured step at a time** instead of by feel.

## Learning objectives
1. Structure a system prompt (role, priorities, policies with reasons, procedures, boundaries, style) and spot prompt
   smells.
2. Design tools as an *agent–computer interface*: names, descriptions, schemas, return values and errors that make the
   right action obvious and the wrong one hard.
3. Write error messages a model can recover from.
4. Use examples (few-shot) deliberately, knowing what they cost.
5. Run prompt/tool changes as experiments: hypothesis, one change, paired measurement, changelog, held-out check;
   tell "better" from "didn't break anything" (non-inferiority), and know why many experiments and peeking mislead.
6. Decide between one prompt for all vendors and per-vendor variants, with data.

---

## §1 Everything in the context is a prompt

The model sees one token stream (Node 01 §1): your system prompt, the **tool definitions**, the conversation, and
every **tool result**. All of it shapes behaviour. Teams often polish the system prompt and leave tool descriptions as
one-line afterthoughts and errors as raw exceptions, though in an agent most of the context is tools and tool results.

The working loop of this node, which you'll use for the rest of the course:

```
read failures (traces) ─▶ hypothesis ("it picks reason=changed_mind for broken items because the
        ▲                  tool description doesn't say what 'damaged' covers")
        │                                   │
   log result ◀── paired comparison ◀── ONE change (prompt line, tool description, error text)
   (keep or revert)     (same tasks, same model, Node 04)
```

Rules: one change per experiment (otherwise you can't attribute the effect), a written hypothesis *before* running,
and a changelog entry whether it helped or not. Negative results are information.

---

## §2 System prompts

### Anatomy
| Part | Purpose | Shopfront example |
|---|---|---|
| **Role and context** | who it is, who it serves, what world it's in | "Shopfront's support assistant, talking with a signed-in customer" |
| **Goals and priorities** | what matters most when things conflict | "Correctness and customer trust come before speed; never promise what a tool hasn't confirmed" |
| **Policies, with reasons** | rules, plus *why* | "Only discuss this customer's orders, because other customers' data is private and the tools will refuse anyway" |
| **Procedures** | the steps for common tasks | "Refunds: identify the order → pick the reason that matches what the customer said → check eligibility → …" |
| **Boundaries and escalation** | what it can't do, and the exit | "Lost packages, warranty claims and safety issues go to a human via escalate_to_human" |
| **Output style** | tone, length, format | "Two to four sentences; dollars, not cents; reply in the customer's language" |
| **Per-request facts** (last) | what changes between requests | "Today is 2026-11-01." Appended at the very end, see below |

### Principles that hold up across current models
- **Explain the why.** "Check eligibility before refunding *because the tool applies the policy windows and you
  shouldn't compute dates yourself*" generalises to cases the rule didn't anticipate. A bare rule doesn't.
- **Say what to do, not only what not to do.** "Reply in the customer's language" beats "don't always reply in English".
- **Don't shout.** ALL-CAPS, "CRITICAL", "YOU MUST" made older models comply. Current models tend to over-apply
  them, treating one shouted rule as more important than everything else. Use emphasis rarely and only where a
  measured failure justifies it.
- **Resolve conflicts explicitly.** "Be concise" + "explain policy thoroughly" will be traded off arbitrarily. Say
  which wins when.
- **Procedures are for frequent, error-prone paths.** Don't write procedures for things the model already does well.
  Every sentence costs tokens on every turn (and attention, Node 01 §7).
- **Put per-request content last.** Anything that differs between requests (the date, the customer's tier, retrieved
  snippets) goes after the stable text. A prompt cache matches an exact *prefix*: one changed token early invalidates
  everything after it, for every request (Node 01 §3, Node 15). The v1 prompt has `{today}` near the top, which is why
  the lint's `volatile-early` rule fires on it; v2 should not inherit that.
- **Structure long or untrusted material.** Wrap documents, retrieved text and tool output you paste into the prompt
  in clear delimiters (XML-style tags work across vendors: `<policy>…</policy>`), put long reference material
  *before* the instructions and question that use it, and say plainly that text inside those tags is data, not
  instructions. That last line reduces but doesn't remove prompt injection; Node 08 fixes it architecturally.
- **Reasoning models: set effort, don't script thinking.** Current models think before answering, with a budget you
  control (`effort` / `reasoning_effort`, Node 01 §6). "Think step by step" and hand-written reasoning templates add
  little and can make things worse; describe the goal and the checks instead, and treat effort as an experimental
  variable like any prompt line (`opt.effort="low"` vs `"medium"`, task 4). Don't ask a model to reveal or format its
  hidden reasoning; ask for the conclusion and the evidence.

### Prompt smells
Excessive caps and "never/always" absolutes; contradictory rules; rules nobody can verify ("be smart"); lists of 30
rules with no priorities; copy-pasted policy text the tools already enforce; examples that cover only the easy case;
prompts that grew by accretion after every incident with no deletions. The lint you build in this node flags the
mechanical ones.

---

## §3 Tools as an agent–computer interface (ACI)

Anthropic's engineering guidance puts it this way: spend as much effort on the interface between agent and tools as
you would on a human UI. The model reads names, descriptions and schemas and nothing else.

**Names.** Verbs, distinct, unambiguous: `lookup_order` and `get_my_orders` are fine; `get_order` and `fetch_order`
side by side are not. If you serve many tools, namespacing (`orders_lookup`, `orders_cancel`) helps selection.

**Descriptions.** Each should answer: *what does it do, when should I use it (and when not), what does it return,
what are the gotchas?* Three to six sentences is normal for a consequential tool. Example:

> `issue_refund`: Refund an order to the customer's original payment method. Use only after
> `check_refund_eligibility` says eligible, with the same reason. `amount_cents` is in cents (4899 = $48.99) and
> must not exceed `max_refundable_cents` from the eligibility check. Refunds over $200 are queued for human approval
> and are not complete when this returns: tell the customer it is pending. Returns `{refund_id, status, amount_cents}`.

**Schemas.** Make invalid states unrepresentable (*poka-yoke*):
- **enums** for categorical values (`reason`), so the model can't invent `"broken"`;
- **units in names** (`amount_cents`, `timeout_s`);
- per-parameter **descriptions** with an example value;
- `required` and `additionalProperties: false`;
- prefer IDs the model has *seen* (from a previous result) over values it must compute.

**Strict schemas.** The major APIs offer a strict mode for tools (`strict: true` on the definition) that constrains
decoding so arguments always match the schema. It removes a class of malformed calls, at the cost of schema
restrictions (every property listed in `required`, optional ones expressed as nullable, limited keyword support;
check your provider's list). Strict mode guarantees *shape*, not *sense*: an enum stops `"broken"`, but nothing stops
`reason="changed_mind"` for a shattered mug. That's what descriptions are for. Keep validating server-side anyway:
not every provider or local model supports it, and the registry's validator is your floor (Node 02).

**Examples on the tool.** A one-line example inside a parameter description (`"e.g. 4899 for $48.99"`) is the
cheapest few-shot there is. Some APIs also accept full example inputs on the tool definition; where available, use
them for tools with nested or easily-confused arguments, and measure them like any other change (§5).

**How many tools.** Selection accuracy drops as the toolset grows: more near-synonyms, more tokens of definitions
every turn. Rough guidance: up to ~10–20 well-separated tools in context is fine; beyond that, consolidate, namespace,
or **load tools dynamically**: keep a small core in context and let the model search a catalogue for the rest (several
APIs now provide a built-in tool-search tool with deferred loading; MCP servers make this common, Node 11). Dynamic
loading trades context size for an extra step and a new failure mode (the model doesn't search for a tool it needs),
so it's an experiment, not a default.

**Granularity.** Many tiny tools mean more turns and more chances to chain them wrong; one giant tool with modes means
confusing schemas. Consolidate around *tasks*, not your internal API: a `check_refund_eligibility` that returns
`max_refundable_cents` saves the model from computing it. And remember your evals couple to tool names (Node 04
graders reference them): renaming or merging tools means migrating graders, so plan interface changes as migrations.

**Return values.** Results are prompts too:
- return what the model needs for the *next* decision, not your whole row (it re-reads every token every turn);
- human-meaningful fields (`days_since_delivery: 45`, `window_days: 30`) beat raw data it must interpret (two ISO
  timestamps and a policy table);
- include units and formatted amounts where the model will repeat them to a human;
- for large results, paginate or truncate *with a marker* and say how to get more;
- consistent shapes across tools (`{"error": CODE, "message": ...}` for every failure).

---

## §4 Error messages are instructions

When a tool fails, its error is the only guidance the model gets at that moment. Compare:

| Bad | Good |
|---|---|
| `KeyError: 4812` | `No order #4812 on this account. Ask the customer to double-check the number, or call get_my_orders to list their recent orders.` |
| `ValidationError: reason` | `reason must be one of damaged, not_as_described, changed_mind, late_delivery, other. Use "damaged" for items that arrived broken or defective.` |
| `PolicyError` | `Refund not allowed: delivered 45 days ago; the changed_mind window for a standard customer is 30 days. If the item arrived damaged, check eligibility with reason="damaged" (60-day window).` |

A good error message names the problem in the model's terms, says **what to do next**, lists valid options when
there's a closed set, and doesn't leak internals (stack traces, SQL, other customers' data). Error messages are also
the cheapest prompt real estate you have: they appear only when relevant, so they cost nothing on the happy path.

---

## §5 Examples (few-shot)

Examples are the strongest steering signal you can put in a prompt, which is both their value and their danger.
- They work well for **format** (exact output shapes) and for **edge cases** that rules describe poorly ("a customer
  says 'it's busted' → reason damaged").
- Models **copy** them: phrasing, length, even irrelevant details. One example of a refund conversation can make every
  conversation look like a refund conversation.
- Use **several diverse** examples, including a "don't act" case, or none. Prefer putting a micro-example inside the
  tool description where it applies (`"e.g. 4899 for $48.99"`) over long dialogues in the system prompt.
- Measure them like any other change. Examples often help a small model a lot and a large one little or not at all.

---

## §6 Measuring prompt and tool changes

Apply Node 04 directly, with three extra cautions:

1. **Effect sizes vs power.** A 23-task suite can only see ~15-point differences (Node 04 §4). Most single prompt
   tweaks are smaller. So run **focused** experiments: pick the tag where the failure lives (`--tags refund,policy`),
   add tasks to that slice if it's thin, and use more trials there.
2. **Overfitting.** Every change is chosen *because* it fixed dev failures. After ten such changes, the dev score
   overstates true quality. The held-out split is your check, used **once** at the end (or at rare checkpoints).
3. **Regressions elsewhere.** A sentence that fixes refunds can break escalations. Run the whole dev suite before
   accepting a change, not just the target slice. That run asks a different question: not "is it better?" but "did
   it break anything?", which is a **non-inferiority** test. The runner reports `non-inferior` when the whole CI of
   the diff sits above `-margin` (default 5 points): "any loss is smaller than 5 points, with 95% confidence". An
   `inconclusive` full-suite run means you can't rule out a regression bigger than the margin; get more trials or
   tasks before accepting.
4. **Many tests, and peeking.** Each experiment is a test at ~95% confidence, so in twenty experiments expect about one
   `better` on pure noise. Peeking is the same trap in time: running, looking, adding trials, and stopping once it
   says `better`. Defences: decide trials and tasks *before* running (write them in the hypothesis), treat a single
   marginal win as a lead to re-test rather than a result, and let the held-out checkpoint catch what slips through.
   The `insufficient` verdict (fewer than 8 tasks) exists because a bootstrap over a handful of tasks produces
   intervals that look precise and aren't.

The **experiment log** is the artefact that makes this work: one row per change with the hypothesis, the diff, the
measured effect with its interval, and the decision. Six months later it explains why each line of the prompt exists,
and which lines you can safely delete.

**Versioning and model drift.** Prompt and tool names are mutable labels; what you tested is the exact text. The
runner logs a content hash of each variant (prompt + tool specs + options) next to its name, so "v2" in March and "v2"
in June are distinguishable. Re-run the baseline whenever the model changes, including a provider's silent update
behind the same alias: a prompt tuned on one model version is a hypothesis about the next. Pin dated model ids for
experiments (Node 00's registry), and keep the regression suite as the gate for any model upgrade.

**Automated prompt optimisation.** Optimisers search over instructions and few-shot examples against an eval metric:
DSPy's MIPROv2 proposes and Bayesian-searches instruction/example combinations; reflective optimisers such as GEPA
have an LLM read failing traces and propose edits, then keep a population of the best candidates. They work once you
have a trustworthy eval and a stable task, and they're dangerous without one: they optimise your grader's blind spots
faster than you would. Treat their output as a candidate variant: run it through the same experiment runner, and
**hold out tasks the optimiser never saw** (it's tuning on dev even harder than you are). The eval is the hard part
either way.

---

## §7 One prompt or one per vendor?

Vendors train on different conventions (Node 01 §5), and they respond differently to the same text: one follows
procedures literally, another needs the reason spelled out, a small local model needs short, explicit steps and an
example. Options:
- **One shared prompt**: simplest, but tuned for one model and merely tolerated by the others.
- **Shared core + per-vendor addenda**: a few lines that fix measured, vendor-specific failures.
- **Fully separate prompts**: most performance, most maintenance (every policy change happens N times).

The course default is shared core + addenda, decided per vendor by experiment. Keep the policy content in one place
either way.

---

## Design trade-offs

| Decision | Options | Guidance |
|---|---|---|
| Rules in prompt vs in code | prompt / tool / service | invariants in code (Node 02); the prompt explains, tools enforce |
| Tool granularity | fine / task-level / mega-tool | task-level; return derived facts (windows, max refundable) |
| Few-shot | none / one / several diverse | none until a measured failure calls for it; then diverse |
| Emphasis | caps and "must" / plain | plain; emphasise only where measured |
| Vendor variants | shared / addenda / separate | shared core + measured addenda |
| Iteration | many changes then measure / one change per measurement | one per measurement, logged |

## Common failure modes and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Model picks the wrong tool between two similar ones | names/descriptions overlap | distinct names; "use X when…, not Y" in both descriptions |
| Model invents argument values | free-text where an enum or a seen ID belongs | enums; IDs from previous results; examples in parameter descriptions |
| Model loops after an error | error message doesn't say what to do | rewrite the error as an instruction (§4) |
| Fixed one thing, broke another | rule interaction | run the full dev suite; resolve conflicts explicitly in the prompt |
| Dev score climbs, users don't notice | overfitting the dev set | held-out check; flywheel tasks (Node 04 §10) |
| A shouted rule dominates everything | over-emphasis | remove caps; give the reason instead |
| Great on Claude, poor on the local model | vendor/size sensitivity | per-vendor addendum (short steps, an example), measured |
| A "win" disappears on re-run | noise: many experiments, or stopping when it looked good | fix trials up front; re-test marginal wins; held-out check |
| Same prompt name, different results months apart | model drift or an edited prompt under the same name | compare the logged hashes; re-run the baseline on the current model |
| Arguments always well-formed but wrong | strict schema hides a semantic problem | better descriptions and enums; read the traces, not just the error rate |

## Self-check
1. Name three places outside the system prompt where "prompting" happens in an agent.
2. Rewrite this error for a model: `ShopError(code='POLICY')`.
3. Why might adding "ALWAYS check eligibility first!!!" *reduce* overall quality?
4. Your change improves the `refund` slice from 70% to 85% (12 tasks × 3 trials) and the full dev suite from 80% to 82%.
   What do you need before you accept it?
5. When is a few-shot example in the system prompt the wrong tool?
6. You want to rename `check_refund_eligibility` to `refund_quote`. What else must change?
7. The full-suite run of an accepted slice win comes back `inconclusive` with diff −1 [−9, +6]. Accept, reject, or
   what?

<details><summary>Answers</summary>

1. Tool names/descriptions/schemas, tool results (return values), error messages. Also AGENTS.md-style project files
   and retrieved documents.
2. E.g. "Refund not allowed for order 4821: delivered 45 days ago, and the changed_mind window for a standard customer
   is 30 days. If the item arrived damaged, check again with reason='damaged' (60-day window); otherwise explain the
   policy and offer escalation." Problem, the facts, the next actions.
3. Over-emphasis: the model may check eligibility in irrelevant situations (status questions), make extra calls, or
   treat that rule as outranking privacy or escalation rules. Shouting shifts priorities globally.
4. A paired comparison with a CI excluding 0 on the slice (36 trials is little), the full-suite comparison showing no
   regression in other tags, failures read on both sides, and a held-out check at the end of the iteration cycle.
5. When the model already does the task well (no measured failure), when one example would bias every conversation
   toward its shape, or when a rule or a tool-description micro-example would do the job with fewer tokens.
6. Every grader and golden/bad script that references the name (Node 04 suite), any prompt text that mentions it, and
   traces/dashboards keyed on tool names. Plan it as a migration, measure before and after.
7. Neither yet. The CI includes a 9-point loss, beyond a 5-point margin, so you can't claim "didn't break anything".
   Read the failing trials in the tags that dropped; then either add trials/tasks until it's `non-inferior` or worse,
   or narrow the change. Don't accept on the point estimate.
</details>

## Socratic review prompt
> Read nodes/05-prompt-tool-design/TEXTBOOK.md, my prompt in agentlab/assistant/prompts.py (SYSTEM_PROMPT_V2) and my
> experiment log docs/experiments/node05.md. Don't write code. Ask me 6 questions, one at a time, about why specific
> lines of my prompt exist and what evidence supports them. If a line has no evidence, ask whether I'd delete it.
