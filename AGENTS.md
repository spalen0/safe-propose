# Working agreement (agents & contributors)

This repo is in the **build-out** phase. Read this before starting.

## Order of reading
1. `docs/BACKGROUND.md` — why this repo exists (the roboanimals/Katana incident).
2. `docs/ARCHITECTURE.md` — the design and the **tx-definition contract** (the API
   boundary between this engine and a consuming multisig repo). Do not change this
   contract without updating both docs and `examples/scripts/safe_txs.py`.
3. `docs/IMPLEMENTATION_PLAN.md` — milestones and discrete, parallelizable tasks.
4. `docs/TEST_PLAN.md` — what "done" means for tests.

## Picking up work
- Each file in `tasks/` is one self-contained unit with **acceptance criteria** and its
  **dependencies** listed at the top. Only start a task once its dependencies are done.
- Tasks marked `parallel-safe: yes` can run concurrently with other parallel-safe tasks.
- When you finish a task, check off its acceptance criteria in the task file and note
  any contract changes in `docs/ARCHITECTURE.md`.

## Conventions
- **Python 3.11+**, `ruff` for lint/format, `pytest` for tests, type hints required on
  public functions.
- **No network calls without a timeout.** This is the bug this repo exists to avoid.
  Every `requests`/HTTP/RPC call must pass an explicit timeout; default 10s.
- **No secrets in git.** Keys, API keys, RPC URLs with keys, and Telegram chat IDs come
  from env or an Ape keyfile — never from this repo. `.gitignore` already covers
  `.env`/keyfiles. Never print a private key. `examples/.env.example` must stay empty of
  values. Production Safe addresses are public on-chain identifiers: they must not appear
  in `src/safe_propose/` (the engine stays generic) but historical docs, tasks, and
  example fixtures may name the SAM Curator safe.
- **The engine is generic.** No safe addresses, market ids, or chain-specific constants
  in `src/safe_propose/`. Those live in the consuming repo's `scripts/safe_txs.py` /
  `ape-config.yaml`. The only exception is fallback tx-service URLs in `txservice.py`.
- Keep CLI output stable and machine-greppable where the roboanimals bot output was
  (`safe_tx_hash` on dry-run and send; nonce and queue link on send).

## Definition of done (whole project)
A curator can, from a multisig repo PR branch, run
`safe-propose dry-run --fn katana_caps --network katana` and `safe-propose send …`,
get the diff + simulation, and see the tx queued at
`app.safe.global/...safe=katana:0x90D0…6B51` — with no silent hangs, on a maintained
stack, reusable across all the multisig repos.
