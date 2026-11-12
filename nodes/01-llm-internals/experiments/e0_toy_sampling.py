"""E0 (offline, free): what temperature and top-p do to a distribution. Needs YOUR toy_sampler.

    .venv/bin/python nodes/01-llm-internals/experiments/e0_toy_sampling.py
"""
import _common  # noqa: F401  (path setup)
import numpy as np
from rich.console import Console
from rich.table import Table

from agentlab.probe.toy_sampler import empirical_distribution, softmax, top_p_filter

# A toy "next token" distribution after: "Your refund has been ..."
VOCAB = ["issued", "approved", "processed", "denied", "sent", "eaten"]
LOGITS = np.array([3.2, 3.0, 2.6, 1.0, 0.5, -2.0])

console = Console()
t = Table(title="softmax(logits / T)")
t.add_column("token")
temps = [0.2, 0.7, 1.0, 1.5]
for T in temps:
    t.add_column(f"T={T}")
probs = {T: softmax(LOGITS, T) for T in temps}
for i, tok in enumerate(VOCAB):
    t.add_row(tok, *[f"{probs[T][i]:.3f}" for T in temps])
console.print(t)

t2 = Table(title="top-p filter at T=1.0 (which tokens survive?)")
t2.add_column("p")
t2.add_column("surviving tokens")
for p in [0.5, 0.8, 0.95, 1.0]:
    kept = top_p_filter(softmax(LOGITS, 1.0), p)
    t2.add_row(str(p), ", ".join(f"{VOCAB[i]} {kept[i]:.2f}" for i in range(len(VOCAB)) if kept[i] > 0))
console.print(t2)

rng = np.random.default_rng(0)
t3 = Table(title="empirical frequency over 2,000 samples")
t3.add_column("setting")
for tok in VOCAB:
    t3.add_column(tok)
for name, kw in [("T=0 (greedy)", {"temperature": 0}), ("T=0.7", {"temperature": 0.7}),
                 ("T=1.0", {"temperature": 1.0}), ("T=1.0, top_p=0.8", {"temperature": 1.0, "top_p": 0.8}),
                 ("T=1.5", {"temperature": 1.5})]:
    f = empirical_distribution(LOGITS, 2000, rng=rng, **kw)
    t3.add_row(name, *[f"{x:.3f}" for x in f])
console.print(t3)
print("\nNear-tie: 'issued' vs 'approved' differ by 0.2 logits. How often does the 'wrong' one win at T=0.7?")
