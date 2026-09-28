# Task 03 — tx-definition loader, `@txn`, and `ctx`

- depends on: 01
- parallel-safe: yes (with 05/06)
- milestone: M1

## Goal
Implement the API boundary in `docs/ARCHITECTURE.md` → "The tx-definition contract".

## Steps
1. `safe_propose/__init__.py`: export `txn`, a decorator that registers a function in a
   module-level registry keyed by its name. Duplicate name → raise.
2. `loader.py`:
   - `load_definitions(path="scripts/safe_txs.py")` — import the consuming repo's module so its
     `@txn` functions register.
   - `get_definition(name)` — return the fn or raise a clear error listing valid names.
3. Define `ctx` (see architecture doc): `ctx.contract(address, abi=None)`,
   `ctx.network`, `ctx.chain_id`, `ctx.safe_address`, `ctx.const`. Use a frozen
   dataclass. Decide and **document** how `ctx.const` is populated (proposal: import a
   `constants.py`/`constants` dict from the consuming repo, configurable).
4. Update `docs/ARCHITECTURE.md` with the finalized `ctx` shape and `ctx.const` mechanism.

## Acceptance criteria
- [x] Two `@txn` functions register and are retrievable by name; duplicate raises.
      (`registry.py`; `tests/test_registry.py`, `tests/test_loader.py`.)
- [x] Unknown `--fn` raises an error listing available names. (`UnknownDefinitionError`.)
- [x] `ctx` shape documented and matches the implementation. (Frozen dataclass
      `context.Ctx`; decision recorded in `docs/ARCHITECTURE.md`. `ctx.const` loads
      module-level data from a `constants.py`, overridable via `--constants-file`.)
- [x] Unit tests per `docs/TEST_PLAN.md` → Loader/`@txn`.
