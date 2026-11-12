# E5: Self-host an open model on free compute

**After** Node 15 (cost and latency; §6 is the arithmetic this elective feeds). **Estimate** 1–2 days. **Cost** $0
on the free tiers below (Modal needs a card on file and a budget set; the others don't charge).

## Why
"Just run our own model" comes up in every cost review and every privacy review. Doing it once, end to end, on free
compute teaches what it actually involves: picking a model that fits the GPU, a serving engine, a context window,
tool-call parsing, authentication, cold starts, and the throughput numbers Node 15's breakeven needs. You'll serve
an open model on two or three platforms, point the course at it, and measure it.

## Platforms (checked 2026-11; free tiers change often, re-check before you start)
| Platform | What you get | Card? | Serving allowed? | Best for |
|---|---|---|---|---|
| **Modal** (Starter plan) | $30/month of credits; serverless GPUs (T4, L4, A10, L40S, A100, H100), native HTTPS endpoints | yes | yes (web endpoints are the product); no reselling or third-party access | vLLM on an L4 behind an API key |
| **Lightning AI** Studio | a one-time credit grant (5 credits, 25 more with a card; expire after 12 months) for GPU Studios (T4 and up); free Studios restart every 4 hours | optional | yes (documented port forwarding and vLLM guides) | Ollama on a T4, reached over an SSH tunnel |
| **GitHub Codespaces** | 120 core-hours and 15 GB-months of storage per month, CPU only | no | for developing and testing the repo's project: a dev model server for this course fits; production hosting doesn't | a small model on CPU (slow, but real) |
| Kaggle notebooks | T4/P100, ~30 GPU-hours/week | no | unclear for public endpoints: keep it inside the notebook (run your client there, against `127.0.0.1`) | E2 (training) and in-notebook benchmarks |
| Colab (free) | T4 when available | no | **no**: its FAQ forbids remote control, proxies and serving | not for this elective |

## Serving stack in one page
- **Ollama** (simplest; T4 and CPU friendly): OpenAI-compatible `/v1/chat/completions` with tools and streaming, but
  no `tool_choice`, no `n`, no authentication at all, and a default context of 4,096 tokens on machines under 24 GiB
  of VRAM (silent truncation: set `OLLAMA_CONTEXT_LENGTH=16384` and check `ollama ps`). Never expose its port to the
  internet: its API can also pull and delete models.
- **vLLM** (fastest on modern GPUs): `vllm serve <model> --enable-auto-tool-choice --tool-call-parser <parser>
  --api-key ...` (for Qwen3: `--tool-call-parser hermes --reasoning-parser deepseek_r1`, or thinking text leaks into
  answers); fragile on T4 (no bf16/FP8): use Ollama or llama.cpp there.
- **Fit**: on a 16 GB T4, an 8–9B model quantized to 4 bits with a 16k context; on a 24 GB L4, `Qwen/Qwen3-8B-FP8`
  with `--max-model-len 16384`; on 12–16 GB of CPU RAM, a 4B model at single-digit tokens per second.
- **Reaching it**: Modal gives an HTTPS URL; Lightning and Codespaces: an SSH or `gh codespace ports forward`
  tunnel to your laptop (private). If you must use a public tunnel, put authentication in front (ngrok's traffic
  policy can require a bearer token on the free plan; Cloudflare quick tunnels don't support server-sent events,
  which breaks streaming).

## Exercises
1. **[PREDICT]** For each platform you'll use: minutes to the first successful tool call, cold-start time, output
   tokens/second, and the largest context that works.
2. **Serve it** on at least two platforms. Suggested pairs: Modal + Codespaces (one GPU, one CPU), or Lightning +
   Codespaces. Modal: adapt its official vLLM example (`modal.com/docs/examples/vllm_inference`): an L4, the model and
   flags above, a `scaledown_window` of a few minutes, the API key from a Modal Secret, and a workspace budget. Lightning:
   `ollama serve` in a Studio, `ssh -L 11434:localhost:11434 <studio>`. Codespaces: open this repo in a codespace,
   install Ollama, `ollama serve` in a terminal (it keeps the idle timer alive), pull a 4B model, `gh codespace ports
   forward 11434:11434`; stop the codespace when done.
3. **Measure it**: `.venv/bin/python electives/E5-self-hosting/bench_endpoint.py --base-url <url>/v1 --model <name>
   [--api-key-env LLM_API_KEY]`. Run the same script against the free OpenRouter model of the same family for
   comparison. **[LOG]** the numbers against your predictions.
4. **Plug it into the course**: with a tunnel to your laptop's port 11434, `AGENTLAB_ALIAS_LOCAL=ollama:qwen3:4b` in
   `.env` is enough. For any other endpoint, add a provider to `config/models.toml`:
   ```toml
   [providers.selfhosted]
   base_url = "https://<your-endpoint>/v1"
   api_key_env = "LLM_API_KEY"     # the key itself goes in .env
   free = true                     # per-token cost $0 (you pay per hour instead; that's step 5)
   ```
   and set `AGENTLAB_ALIAS_LOCAL=selfhosted:<served model name>`. Run a slice of the Node 04 regression suite on it. Which failures are
   the model, and which are the serving stack (context, tool parsing, thinking text)?
5. **The arithmetic**: feed your measured throughput into `python -m agentlab.perf breakeven` (Node 15 YOU_DO 8) with
   the platform's paid hourly price. At what utilization would it beat the API for Shopfront's support traffic?
6. **[DECIDE]** A half-page recommendation: would you self-host for Shopfront, for which workload (support,
   nightly triage, evals), on what, and what would change your mind? Include what it took to make it secure.

## Clean up
Stop Studios and codespaces, scale Modal apps to zero (or delete them), revoke tunnel tokens, and check each
platform's usage page the next day.

## Check before relying on this
Every row of the platform table (quotas, card requirements, terms); Ollama's current context default; the vLLM flags
for your model family; Modal's current vLLM example.
- https://modal.com/docs/guide/billing · https://modal.com/docs/examples/vllm_inference · https://modal.com/pricing
- https://lightning.ai/pricing · https://lightning.ai/docs/platform/inference/vllm.md
- https://docs.github.com/en/billing/concepts/product-billing/github-codespaces
- https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
- https://docs.ollama.com/api/openai-compatibility · https://docs.ollama.com/context-length
- https://docs.vllm.ai/features/tool_calling.html · https://research.google.com/colaboratory/faq.html
- https://ngrok.com/docs/universal-gateway/examples/ollama
