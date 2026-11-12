"""AGENT-OFF: a prompt-injection detector you write, then break (Node 08 YOU_DO tasks 2 and 3).

Read TEXTBOOK §3-§4 first. Tests: nodes/08-prompt-injection/tests/test_detect.py. Only the standard library.
The ops agent's `filter` defence calls `detect_injection` on every untrusted tool result and withholds anything
scoring >= THRESHOLD. You'll measure it (TPR/FPR on a labelled corpus), then attack it until it fails. That
failure is the lesson: a filter lowers the attack rate, it cannot bound it.
"""
from __future__ import annotations

THRESHOLD = 0.5


def detect_injection(text: str) -> float:
    """Score in [0, 1]: how likely `text` (untrusted DATA: a review, a ticket, an address) tries to instruct an AI
    system rather than inform a human reader.

    Contract (the tests check each item):
    1. Returns a float in [0.0, 1.0]; deterministic; "" -> 0.0; never raises on any str.
    2. Normalise before matching: Unicode NFKC, casefold, and collapse whitespace. Text hidden in Unicode "tag"
       characters (U+E0000–U+E007F) must be decoded (tag char c -> chr(ord(c) - 0xE0000)) and scanned; the mere
       presence of tag characters is itself strong evidence (score >= THRESHOLD).
    3. Decode embedded base64 (runs of 24+ base64 characters that decode to mostly-printable UTF-8) and scan the
       decoded text too.
    4. Flag at least: instructions addressed to an AI/assistant/agent/model; "ignore/disregard/forget (all)
       previous/prior/above instructions"; fake role markers ("SYSTEM:", "[system]", "<|im_start|>", "### system");
       requests to call tools or take actions (refund, send/email ... to, forward, reveal the system prompt);
       markdown images or links whose URL carries data (a query string), and HTML comments.
    5. Acceptance on the given corpus (evals/injections.yaml, dev split): TPR >= 0.85 at THRESHOLD and
       FPR <= 0.15 on its benign look-alikes (reviews that MENTION instructions, systems, refunds, Spanish text...).
    """
    raise NotImplementedError("AGENT-OFF: write detect_injection (Node 08 YOU_DO task 2)")
