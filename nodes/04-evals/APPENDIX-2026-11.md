# Appendix (dated 2026-11-04)

- **Sources for the practices in this node**: Anthropic's engineering posts "Demystifying evals for AI agents"
  (task/trial/grader vocabulary, state-based grading, pass^k for customer-facing agents, "unknown" for judges,
  reading transcripts, starting with 20–50 tasks from real failures) and "Quantifying infrastructure noise in agentic
  evals" (resource settings alone moved an agentic benchmark by ~6 points; recommendations on resource floors, kill
  ceilings, repeated runs, scepticism toward small deltas). The pass@k estimator follows Chen et al. (2021, "Evaluating
  Large Language Models Trained on Code").
- **Judge default** is `gpt-mid` (`config/models.toml [evals]`) because the default graded models include a Claude
  model. But the default matrix *also* includes `gpt-fast`, so the judge shares a vendor with one graded model:
  self-preference could favour it on judged tasks. For the fast-vs-gpt-fast decision, either report the judged slice
  separately, use a third-vendor judge (`--judge open-hosted`), or run both judges and compare. Re-check judge
  agreement whenever you change the judge model or rubric.
- **Structured outputs for the judge**: `json_schema` maps to Anthropic `output_config.format` and OpenAI
  `response_format: json_schema` (strict). Local models through Ollama may ignore it; the judge then returns
  `unknown` on unparseable output, which is the intended failure mode.
- **Eval frameworks** (Inspect, promptfoo, DeepEval, Braintrust, LangSmith, Phoenix evals…) implement the same
  concepts with more polish. After this node you can evaluate them by asking: do they grade state, support pass^k,
  isolate trials, and report intervals?
