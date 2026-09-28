# Task 01 — Project scaffold

- depends on: none
- parallel-safe: yes
- milestone: M0

## Goal
Create the installable package skeleton so all other tasks have a home.

## Steps
1. `pyproject.toml`: package name `safe-propose`, module `safe_propose` under `src/`,
   console entrypoint `safe-propose = "safe_propose.cli:main"`. Python `>=3.11`.
   Pinned deps: `eth-ape`, `ape-safe`, `ape-etherscan`, `ape-alchemy`, `click` (or stdlib
   `argparse`), `requests`. Dev deps: `pytest`, `ruff`.
2. Create empty modules with docstrings: `cli.py`, `config.py`, `loader.py`,
   `engine.py`, `txservice.py`, `render.py`, plus `__init__.py` exporting `txn`.
3. `tests/` dir with a trivial passing test.
4. `ruff` config (line length, import sort) and a `Makefile` or `tox`/`nox` optional.
5. CI workflow `.github/workflows/ci.yml`: install, `ruff check`, `ruff format --check`,
   `pytest`.

## Acceptance criteria
- [x] `pip install -e .` succeeds; `safe-propose --help` runs (even if commands are stubs).
      (Verified editable install + `--help`/`--version`; full dep resolution runs in CI.)
- [x] `pytest` and `ruff check` pass in CI. (33 tests pass; `ruff check`/`format --check`
      clean. CI workflow added at `.github/workflows/ci.yml`, py3.11 + py3.12.)
- [x] Module layout matches `README.md` → "Repo layout (target)". (Plus `registry.py`
      and `context.py` split out so `from safe_propose import txn` stays import-light.)
