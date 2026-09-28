# Task 09 — `send` command (propose via delegate)

- depends on: 04, 05, 06
- parallel-safe: no
- milestone: M2

## Goal
Sign with the delegate/proposer and propose the batch to the Safe Tx Service.

## Steps
1. `cli.py`: `safe-propose send --fn <name> --network <net>`.
2. Always **simulate first** (reuse Task 04); abort on simulation failure.
3. Load the proposer account (Task 05), `safe.add_signatures(safe_tx)` as needed.
4. `batch.propose(submitter=<delegate>)` against the resolved tx-service (Task 06),
   time-bounded.
5. Print the queue link + nonce. Exit non-zero on any failure with a clear message
   (never hang).

## Acceptance criteria
- [x] With propose mocked, `send` builds + computes the safe_tx and calls propose once
      with the expected endpoint (TEST_PLAN Layer 2).
      `tests/test_cli.py::test_send_proposes_once` asserts a single propose against the
      **Katana override URL** (the default ape-safe client rejects 747474 — Task 02b).
      Implemented in `cli.send` + `runtime.propose`/`runtime.load_proposer`; proposes via
      a delegate (`propose_safe_tx` accepts a delegate submitter), time-bounded, with a
      confirmation prompt (`--yes` to skip).
- [x] E2E (manual): a real low-risk tx appears in the Safe queue with the expected nonce
      (TEST_PLAN Layer 3, step 4). **DONE (2026-05-26):** `send` proposed an `approve` tx
      to a 1-of-2 **test safe** `0x767Ac83c68D3B172Dac1b30e2493814d8eFC6C58` on the live
      Katana Safe Tx Service via the delegate `0x96d6…426c`; it appears in the queue at
      nonce 0 (`to`=MultiSend, 0/1 confirmations). Used a test safe to avoid touching the
      SAM Curator multisig. `send` also prints the full EIP-712 SafeTx + `execTransaction`
      calldata for the operator to verify before proposing.
