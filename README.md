# safe-propose

A modern, maintained **Python engine + CLI** for building, simulating, and proposing
Gnosis **Safe** transactions to the Safe Transaction Service — built on
[Ape (ApeWorX)](https://github.com/ApeWorX/ape) + [`ape-safe`](https://github.com/ApeWorX/ape-safe).

It is a **redundant, independent alternative** to the GitHub-Actions / "roboanimals"
flow used in the Yearn multisig repos (which is built on EOL `eth-brownie` +
`multisig-ci` and hung during a Katana dry run). The engine under `src/safe_propose/`
holds **no per-safe data**. Each consuming multisig repo keeps its own transaction
definitions and chain config; the engine loads them, simulates, shows the diff, and
proposes via a delegate key. This repo includes reference examples for that contract.

## Why this exists

The existing roboanimals path:
- depends on **EOL `eth-brownie` 1.21** + a custom `multisig-ci@wavey_edit` fork,
- predates new chains (no Katana/747474 in its chain tables),
- has **no HTTP timeouts**, so a stalled external call (RPC fork or Safe Tx Service)
  hangs the run indefinitely instead of failing fast.

`safe-propose` fixes both by construction: Ape/`ape-safe` are maintained, modern
`safe-eth-py` 7.x already supports Katana, and all HTTP has a default 10s timeout.

See [`docs/BACKGROUND.md`](docs/BACKGROUND.md) for the full incident analysis that
motivated this repo.

## What it does

```
safe-propose dry-run --fn <name> --network <net> [--post-comment]   # simulate; optionally post report
safe-propose send    --fn <name> --network <net>                    # sign with delegate + propose to Safe Tx Service
```

- **dry-run**: prints the PR code diff, builds the batch, **pre-flights** each call in
  batch order on a fork (`eth_call` from the Safe, then applied so later calls see earlier
  state changes; `send` pre-flights the same way before proposing), and prints **what a wallet shows so a signer can verify** —
  the full EIP-712 SafeTx preview, each inner call's calldata, and `safe_tx_hash`.
  The preview includes its nonce, but there is no proposal nonce/queue footer because
  nothing is queued. Sending can select a different, queue-aware nonce and hash.
  `--post-comment` mirrors the roboanimals bot by
  posting the block to the PR via `gh`, without the code diff. Decoded arguments are
  formatted as JSON with full addresses and hex bytes; raw calldata stays copyable in
  collapsed sections. A failed pre-flight exits nonzero after printing/posting the report.
  Simulation uses zero gas price because the Safe is the inner-call sender; native-value
  transfers still require its real balance. RPC errors and contract reverts are reported
  separately, and a failed gas estimate is shown as an advisory diagnostic.
- **send**: proposes the batch to the Safe Transaction Service with the delegate
  (proposer) key — printing the same wallet-verifiable calldata before queuing, and using
  the **queue-aware** nonce from the service. Pass `--nonce N` to target a specific nonce —
  e.g. to **replace** a tx already queued at that nonce (the roboanimals `nonce_arg`
  equivalent). Never silently hangs — all network calls are time-bounded.

## Integrating into a multisig repo

The engine holds no per-safe data. A consuming multisig repo supplies the transaction
definitions, the chain config, and the secrets; the engine loads them from the repo's
working directory.

```
safe-propose (this repo)         consuming multisig repo
─────────────────────────        ────────────────────────────────────────────────
engine + CLI (generic)   <────   scripts/safe_txs.py   # tx definitions (@txn fns)
loads tx defs by name            ape-config.yaml       # networks you use
simulate / diff / propose        GitHub secrets / env  # delegate key, RPCs, API keys
```

### 1. Add these files

```
your-multisig-repo/
  scripts/safe_txs.py                   # @txn transaction definitions
  ape-config.yaml                       # copy of examples/ape-config.yaml
  requirements.txt                      # ape-foundry (the dry-run fork provider)
  .github/workflows/safe-propose.yml    # copy of examples/.github/workflows/safe-propose.yml
```

- **`scripts/safe_txs.py`** — one `@txn` function per transaction. The function name is
  what you pass as `fn=` / `--fn`; its docstring is the fallback description. See
  [`examples/scripts/safe_txs.py`](examples/scripts/safe_txs.py):

  ```python
  from safe_propose import txn


  @txn
  def katana_caps(batch, ctx):
      """Submit Morpho supply caps for the Katana vaults."""
      vault = ctx.contract("0x...")
      batch.add(vault.submitCap, market_params, 6_000_000 * 10**6)
  ```

  `ctx.contract(address, abi=None)` returns an Ape contract; pass `abi=` on chains without
  an explorer (Katana). Constants for `ctx.const` load from `constants.py` if present
  (`--constants-file` to override). Use `--txs-file` for a definitions module elsewhere.
- **`ape-config.yaml`** — copy [`examples/ape-config.yaml`](examples/ape-config.yaml) and
  delete the chains you do not use. Keep the `safe` and `foundry` plugins, and keep each
  chain's `custom`, `node`, and `foundry.fork` entries together.
- **`requirements.txt`** — must include `ape-foundry>=0.8,<0.9`; dry-run forks through
  it. Do **not** list `safe-propose` here: the workflow installs the engine itself and
  fails if `requirements.txt` replaces that build.
- **`.github/workflows/safe-propose.yml`** — copy the template unchanged, then adjust the
  `workflow_dispatch` default network if Katana is not your main chain.

### 2. Pin the engine commit

Set the repository variable `SAFE_PROPOSE_REF` to a reviewed 40-character commit SHA of
this repository. It is the only place the engine version is pinned; bump it to upgrade:

```bash
git ls-remote https://github.com/spalen0/safe-propose.git master
```

### 3. Register the proposer

`send` signs with `PROPOSER_PRIVATE_KEY`. That address must be an **owner** or a
**registered delegate** of the Safe on every chain you send on — delegates are registered
per chain. Register it in the Safe web app or with `ape safe delegates add`. Dry-run
needs no proposer.

### 4. Set secrets and variables

Settings → Secrets and variables → Actions. Set only the rows for the chains you use.

**Secrets**

| Name | Needed for | Purpose |
|---|---|---|
| `PROPOSER_PRIVATE_KEY` | `send` | Owner or registered delegate key that proposes the transaction. |
| `<PREFIX>_RPC` | each chain you use | Fork-capable RPC URL (anvil forks it for simulation). One per chain: `ETH_RPC`, `BASE_RPC`, `ARB_RPC`, `OP_RPC`, `HYPEREVM_RPC`, `KATANA_RPC`, `RISE_RPC`, `ROBINHOOD_RPC`. |
| `APE_SAFE_GATEWAY_API_KEY` | `send` on gateway chains | Safe API key for `api.safe.global` (Ethereum, Base, Arbitrum, Optimism, HyperEVM, Robinhood). Not needed for Katana or RISE. |
| `ETHERSCAN_TOKEN`, `BASESCAN_TOKEN`, `ARBISCAN_TOKEN`, `OPTIMISTIC_ETHERSCAN_TOKEN` | optional | Explorer ABI lookups for `ctx.contract` without `abi=`. |
| `TELEGRAM_TOKEN` | optional | Bot token for the "tx queued" message (`send --notify`). |

**Variables**

| Name | Needed for | Purpose |
|---|---|---|
| `SAFE_PROPOSE_REF` | always | Engine commit SHA (step 2). |
| `ETH_SAFE_ADDRESS` | fallback | Safe address used for any chain without its own `<PREFIX>_SAFE_ADDRESS`. |
| `<PREFIX>_SAFE_ADDRESS` | each chain whose Safe differs | e.g. `KATANA_SAFE_ADDRESS`. Set it explicitly on new chains; the CLI warns when it falls back to `ETH_SAFE_ADDRESS`. |
| `TELEGRAM_CHAT_ID` | optional | Telegram group id for `send --notify`. |

The workflow uses the built-in `GITHUB_TOKEN` for PR comments, labels, closing the PR,
the reminder issue, and branch deletion — no personal access token is needed.

### 5. Try it

Open a PR that adds a `@txn` function and comment:

```
/safe-propose fn=<name> network=<net> send=false
```

The dry-run report is posted back to the PR. See [Running from a PR](#running-from-a-pr)
for sending.

### Running locally

```bash
python -m pip install "safe-propose @ git+https://github.com/spalen0/safe-propose.git@master" \
  "ape-foundry>=0.8,<0.9"
# plus the anvil binary: https://book.getfoundry.sh/getting-started/installation
export KATANA_RPC=... KATANA_SAFE_ADDRESS=0x...   # same names as the table above
safe-propose dry-run --fn katana_caps --network katana
safe-propose send    --fn katana_caps --network katana   # also needs PROPOSER_PRIVATE_KEY
```

The CLI reads the environment only; it does not load `.env`. Use
[`examples/.env.example`](examples/.env.example) as a checklist and never commit a
filled copy.

## Running from a PR

[`examples/.github/workflows/safe-propose.yml`](examples/.github/workflows/safe-propose.yml)
is a drop-in workflow for a consuming repo that mirrors the roboanimals PR-comment UX:

```
/safe-propose fn=<name> network=<net> send=<true|false> sha=<40-char-hex>
```

Typical comments on a consuming-repo PR (write access required):

```
/safe-propose fn=katana_caps network=katana send=false
/safe-propose fn=katana_caps network=katana send=true sha=<40-char-hex>
```

Dry-run always posts the simulation + transaction data + `safe_tx_hash` to the PR
(no proposal nonce/queue footer, because nothing is queued). `send=true` then signs
with the delegate, proposes to the Safe Tx Service, labels and closes the PR, and
(optionally) notifies Telegram. `send=true`
must include `sha=` equal to the current PR head so a later push cannot ride an
earlier approval — copy it from the PR Commits tab, or `git rev-parse HEAD` on the
PR branch. If the branch moved, re-comment with the new SHA. Dry-run may omit `sha=`.
Also runnable from the Actions tab (`workflow_dispatch`); that path does not need
`sha=`. Only repo OWNER/MEMBER/COLLABORATOR comments can trigger it (the job then
requires write/maintain/admin on the repository), and commented PRs must use a
branch in the same repository. Fork PRs are rejected because their code would
otherwise run with RPC and proposer credentials. The workflow checks out the
verified PR commit before running it. Setup and the secrets it needs are in
[Integrating into a multisig repo](#integrating-into-a-multisig-repo).

`send --close-pr` creates/applies the nonce label (e.g. `katana #20`, `eth #53`), then
closes the PR after successful pre-flight and proposal. `--label-pr` only labels it.
After notification and reminder attempts finish, `--close-pr` deletes the remote source
branch. Fork branches and the repository's default branch are skipped; local branches
are retained. Deletion failures are reported without resending the transaction.
Dry runs and failed proposals never label or close the PR. The label uses the nonce
actually proposed, which can differ from the dry-run nonce. GitHub needs
`pull-requests: write`, `issues: write`, and `contents: write` permissions. If a GitHub update fails, the
transaction remains queued: fix the PR manually without sending the transaction again.
Existing consuming workflows must add `--close-pr` to their send command and grant
`issues: write` for label creation and `contents: write` for branch deletion.

## Re-evaluation reminder

`send --reminder` opens a GitHub issue on the PR's repo, **assigned to the PR author**,
asking them to re-evaluate (and sign or cancel) the queued transaction:

```
safe-propose send --fn <name> --network <net> --reminder
```

It needs no secrets beyond the workflow's built-in `GITHUB_TOKEN` (`issues: write`). It is
opt-in and fails soft — if there's no PR or `gh` isn't available, the send still succeeds.

## Telegram notifications

`send --notify` posts a "tx queued" message to Telegram. With `--close-pr`, it sends
only after PR labeling and closure succeed:

```
✍️ eth #53 "set flow caps to 0 for oeth"
Sender: "alice"
Description: "set flow caps to 0 for oeth/usdc market for ousd vault"
Review the code, verify the output, and view queued tx on safe
```

- **Setup:** create a bot with [@BotFather](https://t.me/BotFather) → set `TELEGRAM_TOKEN`;
  add the bot to your group and set `TELEGRAM_CHAT_ID` (the group id, e.g. `-1001234567890`;
  find it via `https://api.telegram.org/bot<TOKEN>/getUpdates` or @RawDataBot). Unset → skipped.
- **Links:** "Review the code" opens the PR's files tab; "verify the output" opens the PR;
  "view queued tx on safe" opens the proposed Safe transaction by hash. Custom Safe web URLs without
  the standard `/transactions/queue` route retain their configured queue link.
- **Content:** `#<nonce>` and network shortname are automatic; **title/description** use
  the PR title and body (override with `--title` / `--description`). An empty body uses
  the message title. If PR metadata is unavailable, a diagnostic is printed and the
  function docstring/name is used, with only the Safe link. **Sender**
  defaults to `GITHUB_ACTOR` in CI or your local `git config user.name` (override `--sender`).
- In the workflow, pass `TELEGRAM_TOKEN` as a secret and `TELEGRAM_CHAT_ID` as a repo
  variable (already wired in the template).

## Supported chains

| `--network` | Aliases | Chain ID | Env prefix | Safe Tx Service | Gateway key |
|---|---|---|---|---|---|
| `ethereum` | `eth`, `mainnet` | 1 | `ETH` | Safe gateway (`eth`) | yes |
| `base` | | 8453 | `BASE` | Safe gateway (`base`) | yes |
| `arbitrum` | `arb` | 42161 | `ARB` | Safe gateway (`arb1`) | yes |
| `optimism` | `op` | 10 | `OP` | Safe gateway (`oeth`) | yes |
| `hyperevm` | `hyper`, `hyperliquid` | 999 | `HYPEREVM` | Safe gateway (`hyper`) | yes |
| `katana` | | 747474 | `KATANA` | `safe-transaction-katana.safe.global` | no |
| `rise` | | 4153 | `RISE` | `multisig-txs.risechain.com` | no |
| `robinhood` | `robinhoodchain` | 4663 | `ROBINHOOD` | Safe gateway (`robinhood`) | yes |

The Safe gateway is `https://api.safe.global/tx-service/<slug>/api`. Queue links go to
`app.safe.global`, except RISE, which uses `multisig.risechain.com`.

Per-chain environment, using the env prefix:

- `<PREFIX>_RPC` — required. Must support forking (dry-run and `send` both simulate first).
- `<PREFIX>_SAFE_ADDRESS` — the Safe on that chain; falls back to `ETH_SAFE_ADDRESS`.
- `<PREFIX>_TX_SERVICE_URL` — optional Tx Service override. Keep the trailing `/api`.
- `<PREFIX>_SAFE_QUEUE_URL` — optional Safe web app URL for the queue link.

Every chain must also be declared in the consuming repo's `ape-config.yaml`
(`ethereum:mainnet` is built into Ape and only needs its `node` URI).

## Adding a chain

### In a consuming repo only (no engine change)

Any chain declared under `networks.custom` in `ape-config.yaml` works with
`--network <ecosystem>`:

1. Add the `custom`, `node`, and `foundry.fork` entries, as for the built-in chains in
   [`examples/ape-config.yaml`](examples/ape-config.yaml). Name the network `mainnet` (the
   engine connects to `<ecosystem>:mainnet`) and use a lowercase ecosystem name without
   hyphens (e.g. `mychain`); its uppercase form is the env prefix (`MYCHAIN`).
2. Set `MYCHAIN_RPC`, `MYCHAIN_SAFE_ADDRESS`, and `MYCHAIN_TX_SERVICE_URL` (the chain's
   Safe Tx Service base URL ending in `/api`). The engine has no built-in Tx Service for
   such a chain.
3. In the workflow, add `MYCHAIN_SAFE_ADDRESS` to the job `env`, and `MYCHAIN_RPC` (plus
   `MYCHAIN_TX_SERVICE_URL`) to the env of both the Dry-run and Send steps.

The queue link uses the ecosystem name as the Safe chain prefix (`safe=mychain:0x…`). If
Safe uses a different EIP-3770 prefix for the chain, add it to the engine instead.

### Built into the engine (PR to this repo)

1. `src/safe_propose/config.py` — add a `NetworkSpec` to `NETWORK_SPECS` (name, chain id,
   env prefix, EIP-3770 prefix for the queue link, optional custom queue URL) and any
   aliases to `NETWORK_ALIASES`.
2. `src/safe_propose/txservice.py` — if Safe's gateway serves the chain, add its slug to
   `GATEWAY_SLUGS` (it can differ from the EIP-3770 prefix, as for HyperEVM); otherwise
   add the standalone service to `OVERRIDE_URLS` (base URL ending in `/api`).
3. Examples — add the chain to `examples/ape-config.yaml`, `examples/.env.example`, and
   the env blocks of `examples/.github/workflows/safe-propose.yml`.
4. Tests — cover the new network in `tests/test_config.py` and `tests/test_txservice.py`.

## Local demo (no Safe Tx Service)

Prove the whole build→sign→land pipeline against a Safe, **locally**, with no external
Safe Transaction Service: it forks the chain with anvil, deploys a throwaway **1-of-1
Safe you own**, builds a tx through the engine, signs as the owner, and executes it
on-chain — then reads the result back.

```bash
uv sync --extra dev            # eth-ape, ape-safe, ape-foundry (from uv.lock)
# plus the anvil binary: https://book.getfoundry.sh/getting-started/installation
export KATANA_RPC=...       # or KATANA_RPC_2 — a fork-capable Katana RPC
make demo-local                 # python scripts/local_demo.py
# → [4/5] executed on-chain (gas=...)  /  DEMO: OK
```

This is the local equivalent of `send` without the Tx Service: because you own the Safe,
signatures are real (no impersonation) and the tx actually executes. The production
`send` path instead *proposes* to the Tx Service for the real owners to sign.

For the full operator flow (local sanity → `dry-run` → gated live `send`), see
[`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## License

GNU Affero General Public License v3 or later. See [`LICENSE`](LICENSE).
