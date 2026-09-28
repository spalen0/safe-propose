# Task 10 — Reference examples

- depends on: 03
- parallel-safe: yes
- milestone: M3

## Goal
Provide a copy-pasteable reference of what a consuming repo supplies.

## Steps
1. `examples/scripts/safe_txs.py`: port `katana_caps` from
   `sam-curator-multisig/scripts/morpho.py` to the `@txn(batch, ctx)` contract, reusing
   the same vault addresses / market ids / caps (as fixtures).
2. `examples/ape-config.yaml`: the custom Katana network (chain 747474,
   `base_ecosystem_plugin: ethereum`) + provider URI via `${KATANA_RPC}`, plus
   built-in chains.
3. `examples/.env.example`: list required env (no values): `KATANA_RPC`,
   `APE_SAFE_GATEWAY_API_KEY` (or override), `PROPOSER_PRIVATE_KEY` or keyfile name,
   `*_SAFE_ADDRESS`, `*SCAN_TOKEN`.

## Acceptance criteria
- [x] `examples/scripts/safe_txs.py` loads and registers `katana_caps` against the real loader.
      `tests/test_examples.py` (loads the module, asserts `katana_caps` registers).
      Note: `katana_caps` uses bare `ctx.contract(addr)`; on Katana (no explorer) the
      consuming repo must pass `abi=`/ship interfaces — documented in ARCHITECTURE 02a/04.
- [x] `examples/ape-config.yaml` connects Ape to Katana. Same custom-network shape used
      in the verified Task 02a/04 spikes (chain 747474, `base_ecosystem_plugin: ethereum`);
      `tests/test_examples.py` asserts the declared chain id.
