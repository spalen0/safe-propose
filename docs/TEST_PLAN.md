# Test plan

Three layers: **unit** (fast, mocked, in CI), **integration** (forked chain, no real
posting), and **e2e** (manual, real Tx Service with the delegate). The non-negotiable
property under test everywhere: **no network call hangs — every call is time-bounded.**

## Layer 1 — Unit tests (CI, no network)
Run on every PR. Mock all HTTP/RPC.

- **Loader / `@txn`** (Task 03):
  - registering two functions makes both discoverable by name;
  - duplicate name raises;
  - unknown `--fn` raises a clear error;
  - a tx fn receives a `batch` and a `ctx` with the documented attributes.
- **Config resolution** (Task 05): precedence CLI > env > config file > default; missing
  required value → actionable error (e.g. "no RPC for katana; set KATANA_RPC").
- **Tx-service resolution** (Task 06):
  - chain id → correct gateway URL;
  - `override_url` bypasses the gateway;
  - **every constructed client carries a timeout** (assert the timeout kwarg/env is set);
  - missing gateway API key with a gateway URL → clear error, not a silent attempt.
- **Render** (Task 07): given a structured simulation result, output contains the diff,
  decoded calls and `safe_tx_hash` in a **stable, greppable** format, without a proposal footer
  (snapshot test). PR-comment body renders from the same structure.
- **Timeout guard (repo-wide):** a test/lint check that asserts no `requests.*` /
  HTTP/RPC call is made without a timeout (grep-based or a fixture that patches
  `requests` to fail if `timeout` is None).

## Layer 2 — Integration tests (forked chain, no real posting)
Use Ape's forked/local provider; do **not** post to a real Tx Service (mock the
propose call or use a throwaway/local service).

- **Katana connect + read** (Task 02a): on a Katana fork, `ctx.contract(vault).MORPHO()`
  returns a non-zero address; ABI resolution works.
- **Build + simulate `katana_caps`** (Task 04): the example fn builds a batch, simulates
  successfully, and yields a deterministic `safe_tx_hash` for fixed inputs.
- **dry-run command** (Task 07): end-to-end against the fork with a mocked diff; finishes
  in **seconds**; output assertions as above.
- **Timeout behaviour** (Task 06/09): point the tx-service at an unroutable host and
  assert the command **fails with a timeout error within ~10s**, never hangs. This is the
  direct regression test for the original incident.
- **send (mocked propose)** (Task 09): with the propose call mocked, `send` simulates,
  "signs", and calls propose exactly once with the expected payload; prints queue link +
  nonce.

## Layer 3 — End-to-end (manual, gated, real delegate)
Documented runbook in `docs/` (not in CI). Run by an operator with the delegate key.

1. **Non-Katana sanity:** `safe-propose dry-run --fn <existing_fn> --network ethereum`
   prints diff + simulation + `safe_tx_hash`, no error.
2. **Katana dry run:** `dry-run --fn katana_caps --network katana` completes in seconds.
3. **Cross-check vs roboanimals:** the engine's `safe_tx_hash` / decoded calldata for
   `katana_caps` **matches a roboanimals dry run** for the same function — proves the two
   independent paths produce the *identical* transaction. (Primary redundancy assurance.)
4. **Katana send (low-risk fn first):** `send --fn <small_fn> --network katana` queues a
   tx visible at `app.safe.global/...safe=katana:0x90D0…6B51` with the expected nonce
   (compare with PR #81 nonce-19 behaviour). Verify it appears for the Safe owners to
   sign.
5. **Reuse check** (Task 13): repeat step 1 from `sam-multisig` with its own
   `scripts/safe_txs.py` — works unchanged.

## CI
- GitHub Actions: `ruff check`, `ruff format --check`, `pytest` (Layers 1 + the
  fork-based Layer 2 tests that can run headless, e.g. with an Ape fork + cached RPC).
- Coverage target: focus on `loader`, `config`, `txservice`, `render` (the logic);
  network glue is covered by Layer 2/3.

## Test data / fixtures
- SAM Curator Safe `0x90D0…6B51`; delegate `0x96d6…426c`; Katana 747474.
- Example market ids / vault addresses copied into `examples/scripts/safe_txs.py` from
  `sam-curator-multisig/scripts/morpho.py` (keep in sync; they are test fixtures only).
- A recorded roboanimals dry-run output for `katana_caps` to diff against in step 3.
