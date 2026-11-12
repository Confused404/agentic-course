# promo: house rules

- Money is integer cents everywhere. Never use float for money.
- Public behaviour is specified in BACKLOG.md; read the feature's spec in full before coding.
- Add tests for every behaviour you implement in tests/ (one file per feature: tests/test_f1.py, tests/test_f2.py, ...).
- Never edit or delete existing tests to make them pass. Never edit features.json except as instructed.
- Run the full test suite before you say you're done: `python -m pytest -q`.
- Standard library only.
