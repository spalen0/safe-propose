# Background — why this repo exists

## The existing system (roboanimals)

The Yearn multisig repos (e.g. `sam-curator-multisig`) queue transactions to a Gnosis
Safe via **GitHub Actions**:

- `.github/workflows/slash-command.yml` — a PR comment
  `/run fn=<name> network=<net> send=<true|false>` triggers
  `peter-evans/slash-command-dispatch`.
- `.github/workflows/run-command.yml` — a `workflow_dispatch` that calls the reusable
  `yearn/yearn-workflows/.github/workflows/roboanimals-workflow.yml@v0.10.0`.
- The reusable job: forks the target chain with `anvil --fork`, runs a brownie function
  via `python3 -m multisig_ci brownie run -r main <fn> --network <net>-main-fork`,
  simulates (dry run), and on `send=true` signs with a **delegate `PRIVATE_KEY`** (a
  GitHub secret) and **proposes** (does not execute) the transaction to the **Safe
  Transaction Service**. It then notifies Telegram and labels the PR with the nonce.

Transactions are defined as `@sign`-decorated Python functions (e.g.
`scripts/main.py` → `scripts/morpho.py`) using `ape-safe`/`brownie-safe` syntax. The
Safe address used is the same on every chain (for SAM Curator: `0x90D0…6B51`).

## The incident (2026-05-25, run 26406143947)

A Katana dry run (`/run fn=katana_caps network=katana send=false`) **hung with zero
output for ~15 minutes** on the workflow step "Run Function". A sibling run was
auto-cancelled at 16 minutes. Earlier identical katana-capos attempts behaved the same.

### Root cause: an external Katana call with no timeout, in an EOL stack that predates Katana

- The pinned stack is `multisig-ci @ git+https://github.com/yearn/yearn-multisig-ci-scripts.git@wavey_edit`,
  which uses **`eth-brownie==1.21.0` (EOL / unmaintained)** and an **old `safe-eth-py`**
  whose Safe Tx Service URL map has **no Katana (chain id 747474)** entry.
  `multisig_ci/safes.py` likewise has no 747474 branch — it silently falls back to
  `ETH_SAFE_ADDRESS` (harmless only because the Safe address is identical across chains).
- For a **dry run**, the first external Katana call is the **anvil fork from the Tenderly
  Katana gateway** (`network-config.yaml` host `katana.gateway.tenderly.co/<gateway-key>`).
  Brownie blocks waiting for the forked node to come up before printing anything — which
  matches the observed silent multi-minute hang. A stalled / rate-limited / revoked
  gateway key hangs forever.
- For a **send**, there is a second no-timeout hazard: the repo's
  `scripts/ahhh_im_noncing.py::pending_nonce_override` does `requests.get(url)` **with no
  timeout** against the Safe Tx Service.

### It is not a code regression in the multisig repo

PR #81 (`avkat`) ran `send=true` on Katana successfully on **2026-05-16** — nonce 19 was
queued at `app.safe.global/transactions/queue?safe=katana:0x90D0…6B51`. So:
- Katana's Safe Transaction Service exists and the **delegate-key → Tx Service** path is
  viable, and
- the May 25 failure is **external infrastructure** (most likely the Tenderly Katana fork
  gateway) made *fatal* by the **missing timeouts** in an unmaintained stack.

## Conclusions that shaped this repo

1. **Stay in Python, but move off EOL brownie.** Ape (ApeWorX) is brownie's maintained
   successor; `ape-safe` natively builds multisend batches, simulates, and proposes to
   the Safe Tx Service.
2. **Modern `safe-eth-py` 7.x already supports Katana** (chain shortname `katana`) and
   defaults all Tx Service HTTP to a **10s timeout** (`SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT`),
   returning gracefully for unsupported chains instead of hanging.
3. **Build a redundant path, not a replacement.** The goal is a second, independent
   engine so that when one stack breaks, the other still works.
4. **Make it a shared engine repo.** Several sibling multisig repos exist
   (`sam-multisig`, `strategist-ms`, `chief-multisig-officer`, `sam-curator-multisig`).
   One generic engine serves all of them; per-safe transaction definitions and chain
   config stay in each multisig repo and are reviewed per-PR.

## Reference facts (for implementers)
- SAM Curator Safe: `0x90D0f26025571295D18a6c041E47450B81886B51` (same on all chains).
- Existing delegate / proposer: `0x96d632e41d8c8E7210C39f873B640D1F9998426c`.
- Katana chain id: `747474`. Katana Safe queue URL prefix: `app.safe.global/...safe=katana:`.
- Standalone Katana Safe Tx Service (keyless, to confirm): `https://safe-transaction-katana.safe.global`.
- Safe unified gateway (needs `APE_SAFE_GATEWAY_API_KEY`): `https://api.safe.global/tx-service/{chain}/api`.
- `ape-safe`'s `SafeClient` supports an **`override_url`** to bypass the gateway.
