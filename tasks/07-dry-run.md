# Task 07 — `dry-run` command

- depends on: 04, 05
- parallel-safe: no
- milestone: M2

## Goal
Wire the full validate path and render stable output.

## Steps
1. `cli.py`: `safe-propose dry-run --fn <name> --network <net> [--base <ref>] [--post-comment]`.
2. Resolve config (Task 05), connect Ape, load fn (Task 03), build+simulate (Task 04).
3. `render.py`: produce a block containing
   - **code diff**: `git diff <base>...HEAD` (default base = `master`/`main`),
   - decoded calls + traces + gas,
   - `safe_tx_hash` and the typed-data preview, without a proposal nonce/queue footer.
4. Output must be **stable and greppable** (the hash easy to find).
5. No posting in this task (`--post-comment` handled in Task 08; accept the flag, no-op).

## Acceptance criteria
- [x] `dry-run` on a fork finishes in **seconds** and prints diff + simulation +
      typed-data preview and hash. Verified live against Katana (~8s) with an inline-ABI fn; output
      matched the on-chain `safe_tx_hash`. (`katana_caps` itself needs the vault/Morpho
      ABIs supplied — Katana has no explorer; consuming-repo concern, Task 10/11.) Wired
      in `cli.py`: `runtime.connect(fork=True)` → `engine.simulate` → `render.render_block`.
- [x] Rendered-block test (TEST_PLAN Layer 1) passes. `tests/test_render.py` +
      `tests/test_cli.py::test_dry_run_renders_block` assert the stable, greppable block
      (`safe_tx_hash:` prefix + diff + decoded calls, without a proposal nonce/queue footer).
- [x] **Signer verification (added):** the block prints the full EIP-712 SafeTx (what a
      wallet shows when signing), plus each inner call's calldata. Dry-run data is a
      preview; the send output uses the proposal nonce. Empty-signature execution
      templates are omitted. (`render.render_signable`, `engine.safe_tx_fields`.)
