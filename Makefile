.PHONY: setup check test replay audit secrets build

setup:
	uv sync --locked

check:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
	uv run --locked mypy
	uv run --locked pytest

test:
	uv run --locked pytest

replay:
	uv run --locked rh replay examples/synthetic-replay.json

audit:
	uv run --locked pip-audit --local --skip-editable

secrets:
	gitleaks git --redact --no-banner --log-opts=--all .

build:
	uv build --no-sources
