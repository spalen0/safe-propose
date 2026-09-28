# Operator runbook

How to use `safe-propose` from a consuming multisig repo, from safest to live. Read
[`AGENTS.md`](../AGENTS.md) and [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) first.

## 0. Prerequisites
- `uv sync --extra dev` in this repo, or install the GitHub source in the consuming repo
  as shown in the README.
- The `anvil` binary (foundry) for forked simulation: https://book.getfoundry.sh.
- Exported env (from an untracked `.env` or secret manager): `KATANA_RPC`
  (use a fork-capable Katana RPC), `KATANA_SAFE_ADDRESS`,
  `PROPOSER_PRIVATE_KEY` (the delegate) or an Ape keyfile via `PROPOSER_ACCOUNT`.
  Katana uses the keyless `safe-transaction-katana.safe.global`, so no
  `APE_SAFE_GATEWAY_API_KEY` is needed there.

## 1. Local sanity — no Tx Service, no real queue (safest)
Proves the build→sign→execute pipeline against a Safe you own on a local fork:

```bash
make demo-local        # scripts/local_demo.py
# → DEMO: OK
```

## 2. Dry-run — simulate the real tx, post to the PR (no queue)
Run from the consuming repo's PR branch (it provides `scripts/safe_txs.py` +
`ape-config.yaml`). Override the definition path with `--txs-file` if needed:

```bash
safe-propose dry-run --fn <name> --network katana [--post-comment]
safe-propose dry-run --fn <name> --network katana --txs-file scripts/morpho.py
```
Forks Katana, pre-flights each inner call **in batch order** (`eth_call` from the Safe,
then applied to the fork so e.g. a withdraw funds a later transfer), and prints the code
diff, decoded calls, the **full EIP-712 SafeTx preview**, and `safe_tx_hash`.
`pre-flight (per-call): ok` means no call reverts given the calls before it. `send` runs
the same pre-flight on a fork before proposing from the live node. **Nothing is queued**, so there is no
proposal nonce/queue footer. The preview includes its nonce; sending can choose a
different, queue-aware nonce and therefore a different hash. When signing, cross-check
the send output's `safe_tx_hash` and EIP-712 fields against your wallet.

## 2b. Live send against a **test Safe** (recommended first live run)
Validate the real propose path with zero production impact — against a Safe you own, not
the SAM Curator multisig. The proposer must be able to propose, so the simplest setup is a
**1-of-1 Safe owned by the proposer/delegate** (then it is both owner and proposer; no
separate delegate registration needed). Deploy one (spends a little Katana gas):

```bash
export PROPOSER_PRIVATE_KEY=...     # also funds the deploy
python scripts/deploy_test_safe.py  # → DEPLOYED test Safe: 0x…
export KATANA_SAFE_ADDRESS=0x…      # the printed address
safe-propose send --fn <trivial_fn> --network katana
```
The full pipeline up to the POST is verified (build, on-chain-matching `safe_tx_hash`,
`eth_call` simulation, queue-aware nonce, `SafeClient(override)` construction, proposer
signing) — only the propose itself needs a real safe.

## 3. Live send to the production safe — propose to the queue (operator-gated)
**This queues a real transaction the SAM Curator owners will see.** Pre-checked: the
Katana Tx Service accepts reads for the safe and the delegate `0x96d6…426c` is a
registered proposer (02b/02c).

> Proposer requirement: `propose_safe_tx` only accepts a submitter that is an **owner** or
> a **registered delegate** of the target safe. For the SAM Curator safe the delegate is
> already registered; for a fresh test safe, own it with the proposer key (above) or add
> the delegate via `ape safe delegates add` / the service `/delegates/` endpoint.

```bash
safe-propose send --fn <name> --network katana          # prompts before proposing
#   safe_tx_hash: 0x…
#   nonce: <queue-aware>
#   tx-service: override (timeout=10.0s)
#   Propose this transaction to the Safe queue? [y/N]
```
`send` always simulates first (aborts if any call reverts) and proposes with the delegate
signature. Add `--label-pr` / `--notify` for roboanimals-parity. Verify the tx appears at
`app.safe.global/transactions/queue?safe=katana:<addr>` with the expected nonce, then have
the owners sign.

### First-time live checklist
- [ ] Start with a **low-risk fn** (small/reversible) and confirm the queued nonce matches.
- [ ] Confirm the delegate is registered (`safe-propose` 02c check, or `ape safe delegates`).
- [ ] Keep the proposer key in env/keyfile only — never commit it.
