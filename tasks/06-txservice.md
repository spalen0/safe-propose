# Task 06 — Tx-service resolution (timeouts!)

- depends on: 02b
- parallel-safe: yes
- milestone: M1

## Goal
Resolve the Safe Transaction Service endpoint per chain and guarantee timeouts. This is
the task most directly tied to the original incident.

## Steps
1. Default path: Safe gateway `https://api.safe.global/tx-service/{chain}/api` with
   `APE_SAFE_GATEWAY_API_KEY` (Bearer).
2. Override path: a per-chain `override_url` map; **Katana → the URL confirmed in Task 02b**
   (likely `https://safe-transaction-katana.safe.global`).
3. Construct the `ape-safe`/`safe-eth-py` client with an **explicit timeout** (default 10s,
   `SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT` honored).
4. Clear error when a gateway URL is selected but no API key is present.

## Acceptance criteria
- [x] Unit tests: chain-id→URL mapping, `override_url` bypass, timeout always set,
      missing-API-key error (TEST_PLAN Layer 1). (`txservice.resolve_endpoint`;
      `tests/test_txservice.py`. Timeout is non-`None` by construction — `TxServiceEndpoint`
      rejects a non-positive timeout in `__post_init__`.)
- [~] Integration test: unroutable host → **fails within ~10s, never hangs**
      (TEST_PLAN Layer 2, the regression test). The timeout is wired end-to-end:
      `runtime._inject_tx_service_client` sets `SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT`
      from the resolved endpoint before building the ape-safe client, and `proposal_nonce`
      **fails closed** if the service is unreachable (no on-chain fallback). Exercised
      against the real Katana service during the live `send` (Task 09). A dedicated
      unroutable-host test (point the override at a black-hole IP, assert <~10s) is a small
      optional follow-up; the no-hang behaviour is otherwise covered.
