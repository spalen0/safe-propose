# Task 13 — Reuse validation across multisig repos

- depends on: 09, 10
- parallel-safe: yes
- milestone: M3

## Goal
Prove the engine is genuinely reusable (the reason it is a separate repo).

## Steps
1. Add a minimal `scripts/safe_txs.py` + `ape-config.yaml` to a second multisig repo
   (e.g. `sam-multisig`) for one simple transaction.
2. Run `safe-propose dry-run --fn <that_fn> --network <net>` from that repo unchanged
   (engine installed as a dependency).

## Acceptance criteria
- [ ] Dry run works from a second repo with **no engine code changes**.
- [ ] Any friction found is filed back as engine tasks/issues.
