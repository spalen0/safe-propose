# Task 02 — Spikes / verify open questions

- depends on: 01
- parallel-safe: yes (independent investigations; record findings in docs)
- milestone: M0

> No production code. Output is documented findings in `docs/ARCHITECTURE.md`
> (and corrections to `docs/BACKGROUND.md` if assumptions were wrong).

## 02a — Ape + custom Katana network
- Declare Katana (747474) as a custom Ape network (see `examples/ape-config.yaml`).
- Connect with a real `KATANA_RPC` and read `MorphoVault.MORPHO()` for a SAM
  Curator Katana vault (e.g. `og-usdc` = `0xCE2b8e…29D7`).
- Record: provider config that works, how ABIs resolve (ape-etherscan vs local interface),
  any gotchas.

## 02b — How ape-safe proposes to Katana
- Determine whether proposing uses the Safe **gateway**
  (`https://api.safe.global/tx-service/{chain}/api` + `APE_SAFE_GATEWAY_API_KEY`) and
  whether Katana is in the gateway's chain-id map, **or** whether we must pass
  `override_url=https://safe-transaction-katana.safe.global`.
- Confirm which endpoint **accepts a read** for Safe `0x90D0…6B51` (e.g. GET safe info /
  multisig-transactions). Record the working base URL + auth requirement.

## 02c — Delegate (non-owner) proposing
- Confirm the delegate `0x96d632e41d8c8E7210C39f873B640D1F9998426c` is a registered
  delegate/proposer on the Safe for Katana (and other chains).
- Document how to register a delegate via ape-safe / the Safe API if it is not.

## Status
- **02a — DONE (verified 2026-05-25).** Ape 0.8.50 + ape-safe 0.8.23 connect to custom
  Katana (747474) via the `node` provider and read `MorphoVault.MORPHO()` =
  `0xD50F…8aBc`. ABIs resolve via explicit/inline ABI or a local interface dir, **not**
  ape-etherscan for Katana. Alchemy (`katana-mainnet.g.alchemy.com`) and Tenderly both
  work; Alchemy recommended as primary. Findings in `docs/ARCHITECTURE.md` → Networks.
- **02b — ANSWERED (verified 2026-05-25).** ape-safe 0.8.23's bundled `SafeClient` does
  **not** support chain 747474 (`ValueError: Chain ID 747474 is not a supported chain`),
  so proposing to Katana **requires** an `override_url`. Also surfaced: `create_safe_tx`
  eagerly hits the service even with an explicit nonce, so the engine builds the SafeTx
  offline via `safe.safe_tx_def`. **Live read CONFIRMED (2026-05-25):** GET
  `safe-transaction-katana.safe.global/api/v1/safes/0x90D0…6B51/` → HTTP 200 (nonce 20,
  threshold 2, v1.4.1+L2). So the override URL accepts reads; the only unrun step is the
  actual propose (write), which queues a real tx — operator-gated (Task 09 E2E).
- **02c — DONE (verified 2026-05-25).** `/api/v2/delegates/?safe=0x90D0…6B51` lists the
  delegate `0x96d632…426c`, so it **is** a registered proposer. The delegate→propose path
  is viable with no extra registration. (To register a delegate where missing:
  `ape safe delegates add` / the service `/delegates/` endpoint.)

## Acceptance criteria
- [~] `docs/ARCHITECTURE.md` "Decisions for implementers" + tx-service section updated
      with concrete answers for 02a/02b/02c. (02a recorded; 02b/02c pending.)
- [x] A working `KATANA_RPC` example and the chosen tx-service base URL are recorded
      (URL only — no secrets committed). (Alchemy/Tenderly Katana RPC hosts + the Katana
      override Tx Service URL recorded in `docs/ARCHITECTURE.md`.)
