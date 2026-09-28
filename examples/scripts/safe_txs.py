"""Reference transaction-definition module for a consuming multisig repo.

This is what lives in e.g. sam-curator-multisig/scripts/safe_txs.py. The engine
(`safe-propose`) imports this module so the @txn functions register, then runs the
one selected by `--fn`. The CLI default path is `scripts/safe_txs.py` (override with
`--txs-file`).

NOTE: addresses/market ids below are copied from
sam-curator-multisig/scripts/morpho.py as a worked example. In the real consuming
repo, prefer importing them from a shared constants module (see Task 03 `ctx.const`).
"""

from safe_propose import txn  # provided by the engine (Task 03)

# --- constants (example; real repo may load these into ctx.const) ---
YEARN_KATANA_VAULTS = {
    "og-usdc": "0xCE2b8e464Fc7b5E58710C24b7e5EBFB6027f29D7",
    "og-weth": "0xFaDe0C546f44e33C134c4036207B314AC643dc2E",
    "og-usdt": "0x8ED68f91AfbE5871dCE31ae007a936ebE8511d47",
}

# market ids (bytes32) from app.morpho.org/katana
BUSDT_VBUSDC = "0xcdaf57d98c2f75bffb8f0d3f7aa79bbacda4a479c47e316aab14af1ca6d85ffc"
BUSDC_VBUSDT = "0x6691cdcadd5d23ac68d2c1cf54dc97ab8242d2a888230de411094480252c2ed3"
WEETH_VBUSDC = "0x9f24e1fc2d1779d1e741327e109de381321e2ed862f295221043ceac2576b76e"


@txn
def katana_caps(batch, ctx):
    """Submit Morpho supply caps for the SAM Curator Katana USDT/USDC vaults.

    Mirrors sam-curator-multisig/scripts/morpho.py::katana_caps.
    """
    usdt_vault = ctx.contract(YEARN_KATANA_VAULTS["og-usdt"])
    morpho = ctx.contract(usdt_vault.MORPHO())

    batch.add(usdt_vault.submitCap, morpho.idToMarketParams(BUSDT_VBUSDC), 6_000_000 * 10**6)

    usdc_vault = ctx.contract(YEARN_KATANA_VAULTS["og-usdc"])
    batch.add(usdc_vault.submitCap, morpho.idToMarketParams(BUSDC_VBUSDT), 6_000_000 * 10**6)
    batch.add(usdc_vault.submitCap, morpho.idToMarketParams(WEETH_VBUSDC), 6_000_000 * 10**6)


# Timelocked calls need a method's 4-byte selector and calldata without sending it.
# Every ctx.contract method handler exposes `.selector` next to Ape's `encode_input`.
# The Yearn Katana vaults above are MetaMorpho V1 (no submit/abdicate), so this Morpho
# Vault V2 pattern is shown rather than registered — abdication is irreversible, so a
# real definition should also check the network, Safe, and `vault.abdicated(selector)`:
#
#   vault = ctx.contract(MORPHO_V2_VAULT)
#   selector = vault.setReceiveSharesGate.selector  # HexBytes("0x2cb19f98")
#   batch.add(vault.submit, vault.abdicate.encode_input(selector))
