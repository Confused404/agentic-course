---
name: promo-testing
description: How to write tests for a promo feature that catch the edge cases the backlog cares about (boundaries, rounding, ordering, duplicates, time zones, CLI exit codes). Load before writing tests for any BACKLOG feature.
---

# Testing promo features

For each rule in the feature's spec, write at least one test at the boundary, not just the happy path:

- **Thresholds**: test exactly-at, one-below and one-above (e.g. a minimum spend of 5000: carts of 4999, 5000, 5001).
- **Rounding**: pick amounts where the exact result has a fraction of a cent (999 × 10% = 99.9) and assert the
  floored value.
- **Ordering**: give coupons in an order different from the order of application, and assert `Result.applied` is in
  application order and `Result.rejected` in input order.
- **Case-insensitive codes**: duplicates that differ only in case.
- **Time**: offsets other than UTC (`-05:00`), the exact expiry instant (strictly before means "at" is expired), a
  timestamp without an offset, and `now=None`.
- **CLI**: run it as a subprocess (`sys.executable -m promo explain FILE`), and check stdout lines, stderr's first
  word and the exit code, for good input AND for each kind of bad input.
- **Interactions**: one test per earlier feature that the new one could break (re-run the whole suite too).

Name tests after the rule they check (`test_min_spend_exact_boundary_qualifies`), one file per feature
(`tests/test_f3.py`). Never weaken an existing test to make new code pass.
