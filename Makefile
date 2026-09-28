.PHONY: install dev lint fmt test test-live demo-local all

install:
	uv sync

dev:
	uv sync --extra dev

lint:
	uv run --no-sync ruff check .
	uv run --no-sync ruff format --check .

fmt:
	uv run --no-sync ruff format .
	uv run --no-sync ruff check --fix .

test:
	uv run --no-sync pytest -m "not live"

test-live:
	uv run --no-sync pytest -m live

# Local MVP demo: deploy a 1-of-1 Safe on a local fork, build+sign+execute a tx.
# Needs KATANA_RPC (or KATANA_RPC_2) and the anvil binary.
demo-local:
	uv run --no-sync python scripts/local_demo.py

all: lint test
