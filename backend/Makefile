# ASPIRE backend targets.
#
# `make eval` is the one that gates a merge. It runs offline by default, in
# seconds, with no API key -- so it is something to run before pushing rather
# than something to wait for in CI.
#
# `make eval-live` adds the two model-backed measurements (routing accuracy and
# widget selection). Those need a provider key and take about four minutes.

PYTHON ?= .venv/Scripts/python.exe
ifeq ($(OS),)
PYTHON := .venv/bin/python
endif

.PHONY: eval eval-live eval-json test test-fast lint migrate help

help:
	@echo "eval        the offline evaluation suite (the merge gate)"
	@echo "eval-live   the above, plus the model-backed measurements"
	@echo "eval-json   machine-readable, for CI"
	@echo "test        the whole pytest suite"
	@echo "test-fast   pytest without the slow-marked modules"
	@echo "migrate     alembic upgrade head"

# The gate. Non-zero exit on any threshold breach -- see evals/harness.py.
#
# Run on every PROMPT change, not only on code changes. A one-word edit to a
# system prompt moves the over-trigger rate by five points and nothing about
# the diff says so.
eval: eval-learning
	$(PYTHON) -m evals.harness

eval-live:
	$(PYTHON) -m evals.harness --live
	$(PYTHON) evals/learning_agent.py --live

eval-json:
	$(PYTHON) -m evals.harness --json

# L1-L10 plus the property sweep. Offline by default -- the model is a scripted
# stub, which is what makes L3 ("the widget composer raises") expressible at all
# and what keeps this runnable with no provider key. `eval-live` re-runs the same
# assertions against the configured models.
#
# A dependency of `eval` rather than a separate target somebody remembers: the
# learning agent's prompts are code, and a one-word edit to one moves the
# measured rates by several points with nothing in the diff to say so.
eval-learning:
	$(PYTHON) evals/learning_agent.py

test:
	$(PYTHON) -m pytest

test-fast:
	$(PYTHON) -m pytest -m "not slow"

migrate:
	$(PYTHON) -m alembic upgrade head
