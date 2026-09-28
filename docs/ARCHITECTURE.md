# Architecture

## Two-repo model

```
┌────────────────────────────┐         ┌─────────────────────────────────────────────┐
│ safe-propose (engine)      │         │ consuming multisig repo (sam-curator-multisig)│
│  - CLI (dry-run / send)    │  loads  │  - scripts/safe_txs.py  (tx definitions)     │
│  - tx-def loader           │ ◀────── │  - ape-config.yaml (networks, incl. Katana)   │
│  - build batch + simulate  │         │  - .env / ape keyfile (delegate key, RPC,     │
│  - render diff + output    │         │      APE_SAFE_GATEWAY_API_KEY, scan tokens)   │
│  - propose to Safe TxSvc   │         └─────────────────────────────────────────────┘
│  - generic: NO safe data   │
└────────────────────────────┘
```

The engine is installed into the consuming repo from this GitHub repository (see README)
and run from a PR branch.

## Built on

- **Ape (ApeWorX)** — maintained EVM toolkit (brownie's successor). Provides network
  connection, contract objects, account management, and impersonated simulation.
- **`ape-safe`** — Safe plugin: `safe.create_batch()`, `batch.add(...)`,
  `batch.add_from_receipt(...)` (build from simulated calls), `batch.propose(submitter=...)`.
- **`safe-eth-py` 7.x** (transitive) — knows Katana, 10s default Tx Service timeout.

## Data flow

### `dry-run`
1. Resolve config (network, Safe, RPC, tx-service) from the consuming repo + env.
2. Connect Ape to the target network on a **foundry fork** (custom Katana network if
   `--network katana`); inject the Safe ABI (explorer-less chains).
3. `git diff <base>...HEAD` over the consuming repo → render the code diff in the terminal only.
4. Load `scripts/safe_txs.py` (or `--txs-file`), look up `--fn`, run it against a fresh
   `batch` (`batch.add`).
5. Build the EIP-712 SafeTx (`safe.safe_tx_def`, on-chain nonce) and **pre-flight** each
   inner call **in batch order** via `eth_call` + `estimate_gas` from the Safe
   (`engine.simulate_trace`), applying each passing call to the fork before checking the
   next — a `Contract.method(args) → ok, gas≈N` trace over ordered batch state (see
   "Simulation scope" decision below).
6. Render decoded calls, per-call calldata, the per-call trace, and the full EIP-712
   SafeTx preview with `safe_tx_hash`. The preview retains its nonce, but there is no
   proposal nonce/queue footer because nothing is queued.
7. If `--post-comment`: post the rendered block without the code diff via `gh pr comment`.
   Decoded arguments use indented JSON with full addresses/hex bytes; raw calldata is
   preserved in copyable code blocks inside collapsed sections.
8. Exit nonzero if any call failed, after printing/posting the report.

Per-call checks explicitly use `gasPrice=0`: the Safe is the inner-call sender, while the
executor pays transaction gas. Zero-value calls also get a temporary `state_override` /
`*_setBalance` on the Safe so Anvil/OP-stack gas accounting cannot false-fail a 0-ETH
Safe; native-value transfers still use the real balance. Contract reverts and RPC/transport
errors both fail the pre-flight and are rendered separately. RPC and CLI error text
replaces `http(s)`/`ws(s)` URLs before printing or posting, so a key in an endpoint is
not echoed into the terminal or a PR comment. Gas estimation remains advisory after a
successful `eth_call`, with any estimation error included in the report. Contracts supplied
with an explicit ABI, and trace decoding from cached ABIs, skip explorer fetching.

### `send`
1–4 as above, then:
5. Pre-flight on a **fork** exactly like `dry-run` (ordered batch state); **abort** if any
   call fails — a failing tx is never queued. Only then connect to the **live** node and
   rebuild the batch there; a live `eth_call` cannot carry state between calls, and
   nothing is ever sent on the live node. If the live rebuild encodes different calls
   than the pre-flighted fork batch (the definition read chain state that moved), `send`
   aborts rather than propose calls that were never simulated.
6. Resolve the **queue-aware** nonce from the Tx Service (`runtime.proposal_nonce`,
   fails closed if the service is unreachable) and build the SafeTx; print the same
   wallet-verifiable EIP-712 message and payload and prompt (unless `--yes`).
7. Sign with the delegate/proposer (`propose_safe_tx`) → POST to the Safe Tx Service
   (gateway or `override_url`; Katana uses the standalone service), time-bounded.
8. Print the queue link + nonce; optionally label the PR (`--label-pr`) or label and
   close it (`--close-pr`) / notify Telegram
   (`--notify`, a roboanimals-style message with a "view queued tx on safe" link).
   Labels use the network shortname and proposed nonce, e.g. `katana #20` or `eth #53`.
   Missing labels are created first (existing labels are reused, not `--force`-recolored);
   closing requires successful labeling. GitHub failures
   report that the transaction is already queued and must not be resent to fix the PR.
   Telegram uses the PR title/body and invoking actor, with separate links to the PR
   files, PR, and proposed Safe transaction. When closure is requested, a failed label
   or close operation suppresses Telegram. Metadata lookup and Telegram are time-bounded;
   missing PR metadata falls back to function metadata with a diagnostic.
   After notification and reminder attempts, successful `--close-pr` runs delete the
   remote source branch with a bounded GitHub API call (`contents: write` required).
   Fork branches and the default branch are skipped. Local branches are retained.

## The tx-definition contract (API boundary — keep stable)

A consuming repo provides a module (default **`scripts/safe_txs.py`**, relative to the
process cwd — run the CLI from the consuming repo root). Override with `--txs-file PATH`
if the definitions live somewhere else:

```bash
safe-propose dry-run --fn katana_caps --network katana
safe-propose dry-run --fn katana_caps --network katana --txs-file scripts/morpho.py
```

`--constants-file` is independent and still defaults to `constants.py` (missing file →
empty `ctx.const`). Each transaction is a **named function** discovered by the engine:

```python
# scripts/safe_txs.py  (lives in the consuming multisig repo)
from safe_propose import txn  # tiny decorator from the engine


@txn  # registers under the function name
def katana_caps(batch, ctx):
    """One Safe transaction = one batch of calls."""
    vault = ctx.contract(ctx.const["yearn_katana_vaults"]["og-usdc"])
    morpho = ctx.contract(vault.MORPHO())
    market = morpho.idToMarketParams(WEETH_VBUSDC_MARKET)
    batch.add(vault.submitCap, market, 6_000_000 * 10**6)
```

- `batch` — an `ape-safe` batch; `batch.add(contract.method, *args)` queues a call.
- `ctx` — an engine-provided context object:
  - `ctx.contract(address, abi=None)` → an Ape `Contract` (ABI via ape-etherscan or
    a local interface dir). It is Ape's own `ContractInstance`, so it converts to an
    address, compares/prints as one, and can be passed as a method argument. Every
    method handler (view and state-changing) additionally exposes `.selector` — the
    4-byte id as `HexBytes` (Brownie's `.signature`, but bytes rather than a hex
    string) — next to Ape's `.encode_input(*args)`, so timelocked curator calls can
    `batch.add(vault.submit, vault.abdicate.encode_input(vault.setReceiveSharesGate.selector))`
    (Morpho Vault V2). `.selector` is added once to Ape's `ContractMethodHandler`
    (`safe_propose.selectors`) and hashed by the connected ecosystem, matching
    `encode_input`. Overloaded methods raise `ValueError` on `.selector`; use
    `encode_input(*args)[:4]`.
  - `ctx.network`, `ctx.chain_id`, `ctx.safe_address`.
  - `ctx.const` — optional dict of constants loaded from the consuming repo (addresses,
    market ids) so definitions stay declarative.
- Registration: `@txn` adds the function to a registry keyed by name; `--fn` selects it.
- **Append-only convention:** keep adding new functions for readable PRs (mirrors the
  current `scripts/morpho.py` style). Redefining a name is an error.

Decisions for implementers (record the chosen answer here when made):
- **Exact shape of `ctx` — DECIDED (Task 03).** A **frozen dataclass**
  `safe_propose.context.Ctx` with fields `network: str`, `chain_id: int`,
  `safe_address: str`, `const: MappingProxyType[str, Any]`, and a private
  `_contract` factory. `ctx.contract(address, abi=None)` delegates to the engine-wired
  factory and raises a clear error if called without a live connection (e.g. in a unit
  test). Frozen + a read-only `const` mapping means a definition can only *read* engine
  state and queue calls — it cannot mutate shared state.
- **How `ctx.const` is populated — DECIDED (Task 03).** The engine loads a constants
  module (default `constants.py`, overridable via `--constants-file`) from the consuming
  repo and exposes its **module-level data names** (non-dunder, non-callable,
  non-module) as `ctx.const`. So `AMOUNT = 6_000_000` in `constants.py` is reachable as
  `ctx.const["AMOUNT"]`. `const` is optional — a missing file yields an empty mapping,
  and definitions may instead use their own module-level constants (as
  `examples/scripts/safe_txs.py` does). See `loader.load_constants`.
- **`batch.add` vs `batch.add_from_receipt` — DECIDED (Task 04): prefer `batch.add`.**
  Definitions already carry decoded arguments, so `batch.add(method, *args)` encodes
  straight from the ABI — deterministic and one fewer impersonated execution per call.
  `add_from_receipt` (simulate-then-record) is reserved for cases where a call's
  arguments are only known *after* executing a prior call; it is not the default.
  Consequence: `safe_tx_hash` is a pure function of (calls, nonce).
- **Simulation scope — DECIDED (issue #24).** The pre-send / dry-run check
  (`engine.simulate_trace`) is an **ordered batch-state pre-flight from the Safe**, matching
  how the MultiSend executes: on a fork it takes an `evm_snapshot`, impersonates the Safe,
  checks each call (`eth_call` + `estimate_gas`) and then *applies* it (zero base fee) so
  later calls see earlier state changes — e.g. a vault `withdraw` into the Safe followed by
  `transfer`s of the withdrawn tokens. Failed calls are not applied; the snapshot is
  reverted when the trace ends. Both `dry-run` and `send` run it on a fork and **fail
  closed** (`require_ordered=True`) if the fork lacks `evm_snapshot`/impersonation; only
  direct library callers can fall back to independent checks against the same pre-state. Remaining gap: calls run with the Safe as `msg.sender`, not inside a
  delegatecall `execTransaction`, so Safe guards/modules are not exercised. The
  `safe_tx_hash`/queued tx are unaffected by simulation.

## Config resolution (engine `config.py`)

Precedence: CLI flag → env var → consuming repo config file → built-in default.

| Need                | Source                                                            |
|---------------------|-------------------------------------------------------------------|
| Network + RPC       | consuming `ape-config.yaml` (custom Katana network), `KATANA_RPC` |
| Safe address        | env `<NET>_SAFE_ADDRESS` or config; per chain                     |
| Delegate/proposer   | Ape keyfile account or `PROPOSER_PRIVATE_KEY` env                 |
| Tx Service          | gateway + `APE_SAFE_GATEWAY_API_KEY`, OR `override_url` per chain  |
| Explorer/ABI tokens | `*SCAN_TOKEN` env (ape-etherscan)                                 |

## Supported networks (engine `config.py`)
`NETWORK_SPECS` maps each network → chain id, env prefix, EIP-3770 shortname, scan-token
var. All connect uniformly via the `node` provider with a per-chain `<PREFIX>_RPC`
(declared as custom Ape networks in the consuming `ape-config.yaml`; `ethereum` is core):

| network  | alias | chain id | env prefix | shortname | Tx Service           |
|----------|-------|----------|------------|-----------|----------------------|
| ethereum | eth, mainnet | 1   | ETH      | eth   | gateway              |
| base     |       | 8453     | BASE       | base      | gateway              |
| arbitrum | arb   | 42161    | ARB        | arb1      | gateway              |
| optimism | op    | 10       | OP         | oeth      | gateway              |
| katana   |       | 747474   | KATANA     | katana    | standalone override  |
| hyperevm | hyper | 999      | HYPEREVM   | hyper-evm | gateway (slug `hyper`) |
| rise     |       | 4153     | RISE       | rise      | standalone override  |
| robinhood | robinhoodchain | 4663 | ROBINHOOD | robinhood | gateway              |

## Tx-service resolution (engine `txservice.py`)
- **Gateway** (`GATEWAY_SLUGS` = eth/base/arbitrum/optimism/hyperevm/robinhood):
  `https://api.safe.global/tx-service/{slug}/api` with `APE_SAFE_GATEWAY_API_KEY`
  (required; resolution fails fast without it rather than risking a rate-limited nonce
  read mid-`send`). The slug is Safe's service name, mapped per chain id, and is **not**
  always the EIP-3770 queue prefix: HyperEVM is `hyper` (prefix `hyper-evm`). Templating
  with the prefix 404s.
- **Standalone override** (`OVERRIDE_URLS`): chains the Safe gateway does not serve —
  Katana → `https://safe-transaction-katana.safe.global/api` (note the **`/api`** suffix;
  ape-safe appends paths to it), RISE → `https://multisig-txs.risechain.com/api`. Used even
  when a gateway key is set; both are keyless.
- **Explicit override** (`<PREFIX>_TX_SERVICE_URL` / `SAFE_TX_SERVICE_URL` / CLI): for any
  chain not covered above. A chain with no gateway entry, no built-in override, and no
  explicit URL raises a clear error rather than building a URL that 404s.
- The runtime always hands ape-safe the resolved base URL, and the gateway key is sent
  **only** to `https://api.safe.global`. ape-safe's `SafeClient` otherwise attaches
  `Authorization: Bearer <key>` to every host, which would leak the Safe key to RISE's
  service or an operator-supplied `*_TX_SERVICE_URL`.
- All requests carry an explicit timeout (default 10s).

### Task 02b finding — ape-safe's client does NOT support Katana (VERIFIED 2026-05-25)
ape-safe 0.8.23's bundled `SafeClient.__init__` raises **`ValueError: Chain ID 747474 is
not a supported chain`** — the same class of bug as the EOL `safe-eth-py` in the incident.
Consequences, confirmed on a Katana fork:
- Any code path that builds a `SafeClient` *without* an `override_url` fails on Katana.
  So proposing to Katana **requires** passing `override_url`
  (`safe.get_client(chain_id=747474, override_url=…)`). This validates `txservice.py`'s
  override path; the engine must thread the resolved `override_url` into the client.
- Worse, `SafeAccount.create_safe_tx` computes `nonce=safe_tx_kwargs.get("nonce",
  self.new_nonce)` and Python **eagerly evaluates `self.new_nonce`** (a service call)
  *even when an explicit nonce is given*. So `batch.as_safe_tx` / `batch.as_transaction`
  cannot build a tx offline on Katana at all. The engine therefore builds the EIP-712
  SafeTx **directly via `safe.safe_tx_def(...)` with an explicit on-chain nonce**, fully
  decoupled from the service (see `engine.build_safe_tx`). The queued-aware "next nonce"
  (accounting for already-pending txs) is a `send`-path concern that uses the override URL.

**Live read confirmed (02b/02c, 2026-05-25):** a GET to
`https://safe-transaction-katana.safe.global/api/v1/safes/0x90D0…6B51/` returns HTTP 200
(nonce 20, threshold 2, v1.4.1+L2, 3 owners) — the standalone Katana service is the
correct `override_url`. And `/api/v2/delegates/?safe=0x90D0…6B51` lists the delegate
`0x96d6…426c` (**02c: the proposer is a registered delegate**), so the delegate→propose
path is viable. `send` reads the next nonce from this service (queue-aware) via
`runtime.proposal_nonce`. If the service is unreachable the send **fails closed**
rather than guessing the on-chain nonce (which would conflict with already-queued txs).

## Networks
- Every target chain connects via the **`node` provider** and a per-chain
  `<PREFIX>_RPC` (declared in the consuming `ape-config.yaml`). `ethereum:mainnet` is a
  core Ape network; the others are custom ecosystems with `base_ecosystem_plugin: ethereum`.
- **Katana (747474)** is a custom Ape network (see `examples/ape-config.yaml`).

### Task 04 finding — fork + build + simulate on Katana (VERIFIED 2026-05-25)
- **The incident's hang step is fixed:** `ape-foundry` (anvil) forks Katana via the
  Alchemy RPC in **~7s** (vs the ~15-min silent hang on the EOL Tenderly path). Reproduced
  by `tests/live/test_local_execute.py` → `scripts/local_demo.py` (marked `live`).
- **Hash correctness proven:** the engine's offline `safe_tx_hash` (built via
  `safe.safe_tx_def` + explicit on-chain nonce) **exactly matches the Safe's on-chain
  `getTransactionHash`** for the SAM Curator safe (`0x90D0…6B51`, Safe v1.4.1, 2-of-3).
  This is the primary redundancy guarantee — the engine produces the canonical tx.
- **Explorer-less ABI setup (required on Katana):** since Katana has no ape-etherscan
  explorer, the engine must inject the Safe ABI into the contract cache at **both** the
  Safe proxy address and its **fallback-handler** address (read from storage slot
  `keccak("fallback_manager.handler.address")`) — otherwise `safe.contract` /
  nonce reads raise `ContractNotFoundError`. App contracts (vaults, Morpho) likewise need
  explicit ABIs passed to `ctx.contract(addr, abi=…)` or a local interface dir.
- **On-chain nonce vs `AccountAPI.nonce`:** Ape's `AccountAPI.nonce` is the EOA
  transaction count and shadows the Safe getter, so `safe.nonce` /
  `Contract(addr).nonce` read 0 for a typical Safe. Dry-run reads the contract
  getter via `runtime.safe_onchain_nonce` (`contract._view_methods_["nonce"]`).
  `send` still uses the queue-aware Tx Service nonce.
- **Simulation does not run `execTransaction`.** An earlier spike found that impersonated
  `execTransaction` on ape-foundry reverts `GS025` ("hash not approved") even when the
  hash matches on-chain. `engine.simulate` therefore pre-flights each inner call with
  `eth_call` + `estimate_gas` from the Safe (`simulate_trace`), not an impersonated
  Safe exec. Remaining gap: calls run with the Safe as `msg.sender`, so Safe
  guards/modules are not exercised. The `safe_tx_hash` is unaffected.

### Task 02a finding — Ape + custom Katana connect/read (VERIFIED 2026-05-25)
- Stack confirmed: `eth-ape 0.8.50` + `ape-safe 0.8.23` (safe-eth-py 7.x transitive).
- Connecting `katana:mainnet:node` with the custom network above + a `node:` URI works:
  `provider.chain_id == 747474`, latest block read, and
  `MorphoVault(0xCE2b8e…29D7).MORPHO() == 0xD50F2DffFd62f94Ee4AEd9ca05C61d0753268aBc`.
  Connect took ~10s (one-time Ape provider startup); individual RPC calls are sub-second.
- **ABI resolution:** reading worked with an **explicit/inline ABI**. `ape-etherscan`
  is *not* relied on for Katana (its explorer is unlikely to be in the etherscan plugin's
  chain map); consuming repos should supply ABIs via a local interface dir or pass `abi=`
  to `ctx.contract(...)`. ABI-via-scan-token stays a built-in-chain convenience only.
- **RPC choice (incident-relevant):** both the Tenderly gateway (`KATANA_RPC`) and an
  **Alchemy** node (`KATANA_RPC_2`, `katana-mainnet.g.alchemy.com`) serve every
  fork-relevant method incl. archive/historical state, and both worked through Ape during
  the 2026-05-25 check. The experiment used Alchemy as the primary Katana RPC and Tenderly
  as a fallback. A timeout-bounded multi-RPC failover in `config.py` is a proposed
  follow-up (not yet implemented).
