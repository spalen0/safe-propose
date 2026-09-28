# Implementation plan

Milestones below; each maps to one or more files in `tasks/` with acceptance criteria.
Build order respects dependencies. "parallel-safe" tasks can be run concurrently by
separate agents.

## Milestone M0 — Scaffold & spikes (de-risk the unknowns first)
- **Task 01 — Project scaffold**: `pyproject.toml` (package `safe_propose`, console
  entrypoint `safe-propose`), `src/` layout, `ruff`+`pytest` config, empty modules,
  CI workflow (lint + test). _parallel-safe: yes_
- **Task 02 — Spikes / verify open questions** (no production code; write findings into
  `docs/ARCHITECTURE.md`):
  - a) Connect Ape to **Katana (custom network, 747474)** and read a contract
    (`MorphoVault.MORPHO()`), proving RPC + ABI resolution work.
  - b) Confirm how `ape-safe` proposes to Katana: **gateway + `APE_SAFE_GATEWAY_API_KEY`**
    vs **`override_url`** → `safe-transaction-katana.safe.global`. Which accepts a
    proposal for `0x90D0…6B51`?
  - c) Confirm a **delegate (non-owner)** can propose (the delegate
    `0x96d6…426c`); document how to register a delegate if needed.
  _depends on: 01_

## Milestone M1 — Core engine
- **Task 03 — tx-definition loader + `@txn` + `ctx`**: implement `loader.py` and the
  `txn` decorator/registry; define the `ctx` object per `docs/ARCHITECTURE.md`; load a
  consuming repo's `scripts/safe_txs.py` and resolve `--fn`. Finalize the `ctx`/`ctx.const`
  contract and write it into the architecture doc. _depends on: 01_
- **Task 04 — batch build + simulation** (`engine.py`): given a tx fn, build the
  `ape-safe` batch, simulate (decide `add` vs `add_from_receipt`), and produce a
  structured result (decoded calls, traces, gas, `safe_tx_hash`, nonce). _depends on: 02a, 03_
- **Task 05 — config resolution** (`config.py`): implement the precedence table in
  `docs/ARCHITECTURE.md`; per-network Safe address, RPC, proposer account, scan tokens;
  load consuming `ape-config.yaml`. _depends on: 01_  _parallel-safe with 03/04_
- **Task 06 — tx-service resolution** (`txservice.py`): gateway vs `override_url`,
  per-chain map incl. Katana, explicit timeouts everywhere. _depends on: 02b_

## Milestone M2 — CLI & output
- **Task 07 — `dry-run` command** (`cli.py` + `render.py`): wire config → load fn →
  build+simulate → render **code diff** (`git diff <base>...HEAD`) + simulation +
  `safe_tx_hash`. Stable, greppable output (no proposal nonce/queue footer; nothing is
  queued). _depends on: 04, 05_
- **Task 08 — `--post-comment`**: post the dry-run block to the PR via `gh pr comment`
  (detect PR from branch); no-op gracefully if `gh` unavailable. _depends on: 07_
- **Task 09 — `send` command**: sign with delegate + `propose_safe_tx`, print queue link +
  nonce; reuse the simulate step (always simulate before sending). _depends on: 04, 05, 06_

## Milestone M3 — Examples, parity, docs
- **Task 10 — reference `examples/`**: `scripts/safe_txs.py` (ports `katana_caps` from
  `sam-curator-multisig/scripts/morpho.py`) and `examples/ape-config.yaml` (custom
  Katana network). _depends on: 03_
- **Task 11 — integrate into `sam-curator-multisig`** (in *that* repo, separate PR): add
  `scripts/safe_txs.py`, `ape-config.yaml`, the `SAFE_PROPOSE_REF` engine pin, secrets handling; document
  the curator flow. _depends on: 09, 10_
- **Task 12 — parity extras (optional)**: PR nonce label + Telegram notification to match
  roboanimals. _depends on: 09_
- **Task 13 — reuse validation**: run the engine against a second multisig repo
  (`sam-multisig`) with its own `scripts/safe_txs.py`. _depends on: 09, 10_

## Dependency graph (text)
```
01 ──┬─ 02 ──┬─ 04 ─┬─ 07 ─┬─ 08
     │       │      │      └─ 09 ── 12
     ├─ 03 ──┘      │
     ├─ 05 ─────────┘
     └─ 06 ───────────────── 09
03 ── 10 ── 11
09,10 ── 13
```

## Suggested first wave for parallel agents
- Agent A → Task 01 (scaffold).
- After 01: Agent B → Task 02 (spikes), Agent C → Task 05 (config), Agent D → Task 03
  (loader). These are largely independent.

## Done criteria
See `AGENTS.md` → "Definition of done", and `docs/TEST_PLAN.md` for the gating tests.
