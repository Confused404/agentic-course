# Agentic Engineering course. Run `make help`.
SHELL := /bin/bash
PY := .venv/bin/python
N ?=
BUDGET ?= 1.00
MODELS ?=

.PHONY: help setup seed run check check-env models grade grade-upto eval trace solution new-ticket clean

help:
	@echo "make setup            create .venv, install everything, seed the database"
	@echo "make check-env        keys, which models you get (free or paid) + a live test, Docker, coding agents"
	@echo "make models           verify model aliases exist; refresh OpenRouter prices"
	@echo "make seed             rebuild data/shopfront.db (deterministic)"
	@echo "make run              start Shopfront on http://localhost:8000"
	@echo "make check            Shopfront's own tests"
	@echo "make grade N=02       offline grader for one node (free)"
	@echo "make grade-upto N=05  every node 00..05 + Shopfront (what CI runs: catches regressions)"
	@echo "make eval N=02 BUDGET=2 [MODELS=fast,gpt-fast]   live evals (costs money, capped)"
	@echo "make trace            pretty-print the most recent trace (add ARGS=--full)"
	@echo "make solution N=02    merge the reference solution for a node (escape hatch)"
	@echo "make new-ticket N=02  create a work branch node-02-<you> for the ticket"

setup:
	uv venv --python 3.12 .venv
	uv pip install --python .venv -e ".[dev,otlp]"
	-uv pip install --python .venv -e ".[retrieval]" || echo "retrieval extra failed; only needed from Node 07"
	-uv pip install --python .venv -e ".[mcp]" || echo "mcp extra failed; only needed from Node 11"
	-uv pip install --python .venv -e ".[frameworks]" || echo "frameworks extra failed; only needed in Node 16"
	@test -f .env || cp .env.example .env
	$(MAKE) seed
	@echo "Done. Next: put OPENROUTER_API_KEY in .env, then make check-env"

seed:
	$(PY) -m shopfront.seed

run:
	.venv/bin/uvicorn shopfront.app:app --reload --port 8000

check:
	$(PY) -m pytest shopfront/tests

check-env:
	@$(PY) scripts/check_env.py $(if $(OFFLINE),--offline)

models:
	@$(PY) scripts/check_models.py

grade:
	@test -n "$(N)" || (echo "usage: make grade N=02" && exit 1)
	$(PY) -m pytest -c pyproject.toml --rootdir=. nodes/$(N)-*/tests

grade-upto:
	@test -n "$(N)" || (echo "usage: make grade-upto N=05" && exit 1)
	@dirs="shopfront/tests"; for d in nodes/*/tests; do m=$$(basename $$(dirname $$d) | cut -c1-2); \
	  if [ $$((10#$$m)) -le $$((10#$(N))) ]; then dirs="$$dirs $$d"; fi; done; \
	  echo "grading: $$dirs"; $(PY) -m pytest -c pyproject.toml --rootdir=. $$dirs

eval:
	@test -n "$(N)" || (echo "usage: make eval N=02 BUDGET=2" && exit 1)
	COURSE_BUDGET_USD=$(BUDGET) EVAL_MODELS=$(MODELS) $(PY) -m pytest -c pyproject.toml --rootdir=. nodes/$(N)-*/tests -m live -s -p no:cacheprovider -o addopts="-q --import-mode=importlib"

trace:
	@$(PY) scripts/trace_view.py $(ARGS)

solution:
	@test -n "$(N)" || (echo "usage: make solution N=02" && exit 1)
	@echo "Merging the reference solution for node $(N). If you wrote AGENT-OFF files yourself, git will"
	@echo "report conflicts there: keep yours with 'git checkout --ours <file>' or compare first."
	@if git rev-parse -q --verify solution/node-$(N) >/dev/null; then ref=solution/node-$(N); \
	  else git fetch origin solution/node-$(N) && ref=FETCH_HEAD; fi; \
	  git merge --no-ff -m "Merge reference solution for node $(N)" $$ref

new-ticket:
	@test -n "$(N)" || (echo "usage: make new-ticket N=02" && exit 1)
	@who=$$(git config user.name | tr ' ' '-' | tr A-Z a-z); who=$${who:-$${USER:-me}}; \
	  git switch -c node-$(N)-$$who

clean:
	rm -rf runs/traces/* .pytest_cache
