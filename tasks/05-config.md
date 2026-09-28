# Task 05 — Config resolution

- depends on: 01
- parallel-safe: yes (with 03)
- milestone: M1

## Goal
Implement `config.py` resolving everything the engine needs, per the precedence table in
`docs/ARCHITECTURE.md`.

## Steps
1. Precedence: CLI flag → env var → consuming `ape-config.yaml` / config file → default.
2. Resolve per `--network`: RPC URI, Safe address (`<NET>_SAFE_ADDRESS`), proposer
   account (Ape keyfile name or `PROPOSER_PRIVATE_KEY`), explorer/scan tokens.
3. Read the consuming repo's `ape-config.yaml` for custom networks (Katana).
4. Fail fast with actionable messages when a required value is missing
   (e.g. "no RPC for katana; set KATANA_RPC").
5. Never log secret values.

## Acceptance criteria
- [x] Unit tests cover precedence and missing-value errors (TEST_PLAN Layer 1).
      (`tests/test_config.py`: CLI>env, missing safe/RPC errors, custom-network chain id
      from ape-config, timeout parsing.)
- [x] Returns a typed `Config` object consumed by `cli.py`. (`config.Config`; wired into
      `cli._resolve`.)
- [x] No secret is printed or logged. (`Config.__repr__` redacts `proposer_private_key`,
      `gateway_api_key`, `scan_token`, `rpc_uri`, and `tx_service_url` completely.
      Covered by `test_repr_redacts_secrets`.)
