# Task 11 — Integrate into sam-curator-multisig

- depends on: 09, 10
- parallel-safe: yes (work happens in the *other* repo, via its own PR)
- milestone: M3

## Goal
Wire the engine into `sam-curator-multisig` as the redundant path, without disturbing
the existing roboanimals flow.

## Steps (in the sam-curator-multisig repo, separate PR)
1. Add `scripts/safe_txs.py` porting the `@sign` functions from `scripts/morpho.py` /
   `scripts/main.py` to the `@txn` contract (start with `katana_caps`).
2. Add `ape-config.yaml` (custom Katana network) — base it on `examples/ape-config.yaml`.
3. Pin the engine to a reviewed commit with the example workflow's `SAFE_PROPOSE_REF`
   repository variable — the only pin; do not also list `safe-propose` in a requirements
   file (the workflow fails if `requirements.txt` replaces the pinned build). While the
   engine repo is private, add a read-only `SAFE_PROPOSE_TOKEN` secret; do not commit it.
   For local runs, install that same SHA into a venv isolated from the brownie scripts.
4. Secrets hygiene: keep the proposer key + API keys in an untracked file / Ape keyfile;
   add any new secret files to `.gitignore`. **Do not** rely on committed `.env`.
5. Document the curator flow in that repo's README: `dry-run` → review → `send`.

## Acceptance criteria
- [ ] From a PR branch in sam-curator-multisig, `safe-propose dry-run --fn katana_caps
      --network katana` works. **PENDING** — needs that repo. (The CLI path is proven live
      against a test safe; `katana_caps` additionally needs the vault/Morpho ABIs supplied,
      since Katana has no explorer.)
- [ ] No changes to the existing `.github/workflows/*` (roboanimals stays as-is). The
      redundant path is a **separate** workflow — a ready template is shipped at
      `examples/.github/workflows/safe-propose.yml` (PR comment `/safe-propose fn=… network=…
      send=… sha=…`; actionlint-clean). The consuming repo drops it in alongside roboanimals.
