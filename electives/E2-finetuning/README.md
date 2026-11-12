# E2: Fine-tuning vs the harness

**After** Node 09 (workflows: ticket triage). **Estimate** 1.5 days. **Cost** $0 using Kaggle's free GPU notebooks
(or any GPU you have).

## Why
Node 09 classified 240 support tickets with rules, prompts, votes and cascades. The obvious next question: would a
small model *fine-tuned* on the labels do better, cheaper or faster than a big prompted one? Sometimes yes. Often the
honest answer is "not with 160 examples", and it's worth finding out with your own numbers before anyone proposes a
training pipeline.

## Background
- **What fine-tuning changes**: the model's weights, so a behaviour (format, label set, tone) no longer needs to be
  described in the prompt. It doesn't add knowledge reliably, and it doesn't fix bad labels. LoRA trains a small
  set of extra weights (adapters), which fits a 1–4B-parameter model on a free 16 GB GPU.
- **What it costs**: data preparation, a training run per change, an evaluation run per change, and a model you now
  host or pay to host (E5, Node 15 §6). The prompt it replaces cost you an edit.
- **The comparison must be fair**: same held-out tickets (Node 09's split: ids divisible by 3), same metrics
  (accuracy, macro-F1, cost and latency per ticket), and noise intervals (Node 04). Never train on held-out tickets.
- **Free GPUs**: Kaggle notebooks give a T4 or P100 (16 GB), about 30 GPU-hours a week, 12-hour sessions, after
  phone verification, with no card required. They're for ML work inside the notebook: train and evaluate there.
  Don't expose a notebook as a public server (Kaggle's terms are unclear about tunnels; E5 covers serving properly).
  Colab's free tier forbids remote control and serving, so it's fine for training but not for E5.

## Exercises
1. **Export the data.** `python electives/E2-finetuning/export_triage.py` writes `runs/e2/train.jsonl` (dev split)
   and `runs/e2/eval.jsonl` (held-out) in chat format: the ticket as the user message, `{"category", "priority"}` as
   the assistant's answer. Look at the label distribution. How many examples per category do you have?
2. **[PREDICT]** Macro-F1 on held-out for: your best Node 09 prompt on `fast`; the same prompt on a small open model
   (Qwen3 1.7B–4B or Gemma, via Ollama or OpenRouter); and the small model after LoRA.
3. **Train** in a Kaggle notebook (GPU on, internet on): upload the two files as a dataset; train a LoRA adapter on
   a small instruct model for 2–3 epochs (Unsloth or TRL's `SFTTrainer`; both have Kaggle-ready examples); keep 10%
   of train for early stopping. **[LOG]** the training loss curve, GPU time and memory.
4. **Evaluate in the notebook** on `eval.jsonl` only: parse the JSON answer, compute accuracy and macro-F1 (copy
   `macro_f1` from Node 09), and per-ticket latency. Bring the numbers back; compare with Node 09's table, with
   Wilson intervals.
5. **[DECIDE]** Write the case for and against shipping the fine-tuned model: quality delta and its uncertainty,
   cost per 1,000 tickets including hosting (Node 15's breakeven), the retraining cost when categories change, and
   what you'd try first instead (more few-shot examples? a cascade?).

## Check before relying on this
Kaggle's current GPU quota and verification rules; the current Unsloth/TRL notebook recipes; which small open models
support your chat template.
- https://www.kaggle.com/docs/notebooks · https://docs.unsloth.ai · https://huggingface.co/docs/trl
- https://research.google.com/colaboratory/faq.html (what Colab's free tier forbids)
