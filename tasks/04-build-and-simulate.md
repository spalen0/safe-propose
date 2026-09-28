# Task 04 — Batch build + simulation

- depends on: 02a, 03
- parallel-safe: no (core)
- milestone: M1

## Goal
Turn a selected tx function into a built, simulated Safe transaction with structured
results for rendering.

## Steps
1. `engine.py`: `build(fn, ctx, safe)` → `safe.create_batch()`, run `fn(batch, ctx)`.
2. Decide `batch.add` vs `batch.add_from_receipt` (simulate-then-record). Prefer the form
   that reduces ABI/encoding surprises; **document the choice** in `docs/ARCHITECTURE.md`.
3. `simulate(batch, safe)` → impersonated/forked execution; collect: decoded calls,
   call traces, gas, `safe_tx_hash`, computed nonce. Return a structured dataclass
   (`SimulationResult`) consumed by `render.py`.
4. Deterministic `safe_tx_hash` for fixed inputs (no time/nonce nondeterminism beyond the
   real nonce).

## Acceptance criteria
- [x] `build` + `simulate` produce a `SimulationResult` (`engine.py`). API corrected
      against the real ape-safe 0.8.23 surface (verified on a Katana fork): builds the
      EIP-712 SafeTx via `safe.safe_tx_def` + explicit on-chain nonce (NOT
      `create_safe_tx`, which eagerly hits the Tx Service and fails on Katana — see
      `docs/ARCHITECTURE.md` Task 02b). `add` vs `add_from_receipt` decision recorded
      (prefer `add`).
- [x] Integration test on a Katana fork passes (TEST_PLAN Layer 2).
      `tests/live/test_local_execute.py` → `scripts/local_demo.py` (marked `live`) forks
      Katana, deploys a Safe, and asserts the engine's offline `safe_tx_hash` **equals the
      Safe's on-chain `getTransactionHash`**, then signs + executes it. Per-call revert
      checks use `eth_call` from the Safe (`engine.simulate_calls`) — no impersonated
      `execTransaction`, so no `GS025`.
- [x] No un-timed network calls introduced. (Guarded repo-wide by
      `tests/test_timeout_guard.py`.)
