"""haystack.py: deterministic long documents with a needle at a controlled position."""
from agentlab.probe.haystack import build_haystack, estimate_tokens, needle_position

N = "NEEDLE: the code is 4471."
D = ["DISTRACTOR one 4417.", "DISTRACTOR two 7714."]


def test_deterministic_and_long_enough():
    a = build_haystack(5000, N, 0.5, D, seed=3)
    assert a == build_haystack(5000, N, 0.5, D, seed=3)
    assert a != build_haystack(5000, N, 0.5, D, seed=4)
    assert estimate_tokens(a) >= 5000
    assert "status: current" not in a


def test_positions():
    first = build_haystack(4000, N, 0.0)
    last = build_haystack(4000, N, 1.0)
    mid = build_haystack(4000, N, 0.5)
    assert first.startswith(N) and last.endswith(N)
    assert 0.35 < needle_position(mid, N) < 0.65
    assert needle_position("abc", N) == -1.0


def test_distractors_present_and_needle_once():
    h = build_haystack(4000, N, 0.25, D, seed=1)
    assert h.count(N) == 1 and all(d in h for d in D)


def test_long_haystacks_do_not_repeat_paragraphs():
    h = build_haystack(30000, N, 0.5, D, seed=2)
    paras = h.split("\n\n")
    assert len(paras) == len(set(paras)), "filler must not cycle the small help-center corpus"
    assert estimate_tokens(h) >= 30000


def test_ops_memo_is_deterministic_and_varied():
    import random
    from agentlab.probe.haystack import ops_memo
    a = [ops_memo(random.Random(1)) for _ in range(1)]
    assert a == [ops_memo(random.Random(1))]
    rng = random.Random(3)
    memos = {ops_memo(rng) for _ in range(200)}
    assert len(memos) > 190 and any(ch.isdigit() for ch in next(iter(memos)))
