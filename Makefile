# Common tasks. Every target is a thin wrapper over a command the CI jobs also run, so
# `make check` locally is the same set of gates a pull request faces.
#
#   make install   # editable install with the pinned dev tools
#   make check     # lint + test + coverage ratchet (about 3 minutes)
#   make repro     # regenerate every figure and table from scratch (measured 321 s, about 5 minutes)

PYTHON ?= python
RESULTS ?= results/benchmark.json

.DEFAULT_GOAL := help
.PHONY: help install hooks test lint format cov check bench figures docs-check srs docs docs-serve demo repro docker secrets clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## editable install with the dev tools
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

hooks: ## install the pre-commit hooks
	$(PYTHON) -m pre_commit install

test: ## run the test suite
	$(PYTHON) -m pytest -q

lint: ## ruff, ruff format check, mypy
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts
	$(PYTHON) -m mypy src --ignore-missing-imports

format: ## apply ruff formatting
	$(PYTHON) -m ruff format src tests scripts

cov: ## coverage ratchet (project tracer, not pytest-cov)
	$(PYTHON) scripts/coverage_report.py --ratchet

check: lint srs test cov ## the local gates, in CI order

bench: ## run the benchmark and write results/benchmark.json
	$(PYTHON) -m navkit run --out $(RESULTS) --markdown

figures: bench ## render docs/figures from a fresh benchmark, with the animation
	$(PYTHON) -m navkit figures --results $(RESULTS) --animate

docs-check: ## fail if a documented table disagrees with the benchmark
	$(PYTHON) scripts/check_doc_tables.py --results $(RESULTS)

srs: ## fail if an SRS requirement has no test, config check or declared gap
	$(PYTHON) scripts/check_srs_trace.py

docs: ## build the documentation site with warnings as errors (needs `pip install -e '.[docs]'`)
	$(PYTHON) -m mkdocs build --strict

docs-serve: ## serve the site locally with live reload
	$(PYTHON) -m mkdocs serve

demo: ## generate the demo frames into artifacts/demo
	$(PYTHON) scripts/generate_demo.py --out artifacts/demo

repro: figures ## every number and figure in the docs, from scratch
	$(PYTHON) -m navkit sweep seeds --seeds 10 --markdown
	$(PYTHON) -m navkit sweep scenes --seeds 8 --markdown
	$(PYTHON) -m navkit sweep outages --markdown --csv results/outage_sweep.csv --figure docs/figures/outage-sweep.png
	$(MAKE) docs-check

docker: ## build the container image and run the CLI smoke test
	docker build -t navkit .
	docker run --rm navkit navkit --version

secrets: ## scan the tracked files and the git history for credential-shaped strings
	$(PYTHON) scripts/scan_secrets.py
	$(PYTHON) scripts/scan_secrets.py --history

clean: ## remove caches and generated output
	rm -rf results artifacts build dist site .pytest_cache .ruff_cache .mypy_cache .hypothesis htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
