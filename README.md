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

## How it fits with a multisig repo

```
safe-propose (this repo)         consuming multisig repo (e.g. sam-curator-multisig)
─────────────────────────        ────────────────────────────────────────────────
engine + CLI (generic)   <────   scripts/safe_txs.py  # tx definitions (@txn fns)
loads tx defs by name            ape-config.yaml # networks (incl. custom Katana)
simulate / diff / propose        .env / keyfile  # delegate key, RPC, API keys
```

Install it into a multisig repo and run the CLI from that repo's PR branch. While this
repository is private, provide a read-only access token:

```bash
engine_url="git+https://x-access-token:${SAFE_PROPOSE_TOKEN}@github.com/spalen0/safe-propose.git"
python -m pip install "safe-propose @ ${engine_url}@main"
```

For automation, pin a reviewed 40-character commit SHA. The consuming-repo workflow
template (`examples/.github/workflows/safe-propose.yml`) reads that SHA from the
`SAFE_PROPOSE_REF` repository variable — the single place the engine version is pinned —
and fails if the PR's `requirements.txt` replaces that build, so do not list
`safe-propose` there. While this repository is private, also set a read-only
`SAFE_PROPOSE_TOKEN` secret; once it is public, delete the secret and the template
installs from the public URL. Do not commit a filled `.env`.

Tx definitions are loaded from **`scripts/safe_txs.py`** by default. Point at another
module with `--txs-file`:

```bash
safe-propose dry-run --fn katana_caps --network katana
safe-propose dry-run --fn katana_caps --network katana --txs-file path/to/other_txs.py
```

Constants for `ctx.const` still default to `constants.py` (`--constants-file` to override;
a missing file is fine).

### Robinhood Chain mainnet

Use `--network robinhood` (or `robinhoodchain`) for chain ID 4663. In the consuming
repo, declare the `robinhood` custom network, node URI, and foundry fork as shown in
[`examples/ape-config.yaml`](examples/ape-config.yaml). Set `ROBINHOOD_RPC` and
`ROBINHOOD_SAFE_ADDRESS` in the untracked env. Set it explicitly: when it is unset the
engine falls back to `ETH_SAFE_ADDRESS` (and prints a warning), and a new chain's Safe is
rarely at the Ethereum address. The RPC should support forked simulation.

`send` uses Safe's gateway at `https://api.safe.global/tx-service/robinhood/api` and
requires `APE_SAFE_GATEWAY_API_KEY`, as on the other gateway chains. Its queue link uses
the Safe prefix `robinhood` (`app.safe.global/...?safe=robinhood:0x...`).
No Robinhood Safe address or transaction definition is bundled with the engine.

## Repo layout

```
safe-propose/
  README.md
  LICENSE                    # GNU AGPL v3 or later
  AGENTS.md                  # working agreement for agents/contributors
  pyproject.toml             # package + console entrypoint + dependency ranges
  src/safe_propose/
    __init__.py              # exports `txn`
    registry.py              # @txn decorator + name registry
    loader.py                # load consuming repo's scripts/safe_txs.py / constants.py
    context.py               # the frozen `ctx` handed to tx definitions
    config.py                # resolve network/safe/tx-service/account config
    txservice.py             # Safe Tx Service / gateway resolution + override_url
    engine.py                # build batch, build SafeTx, pre-flight
    runtime.py               # Ape connection, Safe load + ABI injection, propose
    render.py                # diff + simulation + full calldata block, PR-comment body
    gitutil.py               # git diff + gh PR detect/comment (timeout-bounded)
    notify.py                # PR nonce label + Telegram "tx queued" message
    reminder.py              # open a "re-evaluate" issue assigned to the PR author
    selectors.py             # 4-byte `.selector` on Ape method handlers
    cli.py                   # click CLI: dry-run / send
  scripts/
    local_demo.py            # `make demo-local`: deploy a Safe on a fork, sign + execute
    deploy_test_safe.py      # deploy a throwaway test Safe on live Katana
  tests/                     # unit (mocked) + tests/live/ (marked `live`); see docs/TEST_PLAN.md
  docs/
    BACKGROUND.md            # incident analysis (why this repo exists)
    ARCHITECTURE.md          # design, data flow, the tx-definition contract, spike findings
    IMPLEMENTATION_PLAN.md   # milestones + discrete tasks (agent-ready)
    TEST_PLAN.md             # unit / integration / e2e test strategy
    RUNBOOK.md               # operator flow: local → dry-run → gated live send
  examples/
    scripts/safe_txs.py      # reference tx-definition module (consuming-repo layout)
    ape-config.yaml          # reference config incl. custom Katana network
    .env.example             # required env (RPC, safe addr, proposer, telegram, …)
    .github/workflows/safe-propose.yml   # drop-in PR-comment workflow (roboanimals parity)
```

## Status

**Engine complete and proven end-to-end on Katana.** Implemented, tested, and merged:
scaffold, the `@txn`/loader/`ctx` contract, config + tx-service resolution, build +
pre-flight simulation, the `dry-run` / `send` CLI (with `--post-comment`, full
calldata for signer verification, PR-label, and a roboanimals-style Telegram message),
the GitHub Actions workflow template, and a local MVP (`make demo-local`).

Verified live: foundry forks Katana in ~7s (the incident's hang step), the engine's
offline `safe_tx_hash` matches the Safe's on-chain `getTransactionHash`, a real tx was
**proposed to the live Katana Safe Tx Service** (queued on a test safe via the delegate),
and a reverting tx is **rejected by the pre-flight before it can be queued**. The Katana
read + the delegate's registration (Tasks 02b/02c) are confirmed against the live service.

**Remaining:** integration into the consuming multisig repos (Tasks 11/13 — landing
`scripts/safe_txs.py`/`ape-config.yaml`/the workflow in `sam-curator-multisig` / `sam-multisig`
and a real Actions run). See `docs/ARCHITECTURE.md` for the recorded findings, `docs/RUNBOOK.md`
for the operator flow, and `tasks/*.md` for per-task acceptance status.

## Try it locally (MVP)

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

## Secrets hygiene

Production Safe addresses, RPC URLs, Telegram chat IDs, and API keys belong in the
consuming repo's untracked `.env` / GitHub secrets — not in this engine. Use
[`examples/.env.example`](examples/.env.example) as a template and export the needed
values before running the CLI; the CLI does not load `.env` automatically. The template
itself must stay empty of values. `Config` redacts private keys, gateway keys, scan tokens, and
complete RPC and Tx Service URLs in `repr`. RPC/CLI error text replaces `http(s)`/`ws(s)`
URLs before they are printed or posted as a PR comment, so a provider key in an endpoint
is not echoed. Telegram errors strip the bot token before they are printed.

If a credential is ever committed, revoke or rotate it even after removing it from Git:
it stays in Git history.

## GitHub Actions (redundant roboanimals path)

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
verified PR commit before running it. Secrets/vars it needs are listed at the top
of the file. This is the independent, maintained second engine the project exists
to provide — same trigger ergonomics, no EOL brownie, no untimed hangs.

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

## License

GNU Affero General Public License v3 or later. See [`LICENSE`](LICENSE).
