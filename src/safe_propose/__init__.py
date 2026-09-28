"""safe-propose: a generic engine + CLI to build, simulate, and propose Safe txs.

The public surface a *consuming* multisig repo touches is intentionally tiny: the
:func:`txn` decorator, used in that repo's ``scripts/safe_txs.py`` to register a transaction
definition under its function name. Everything else (loading, config, simulation,
proposing) is driven by the CLI.

    from safe_propose import txn

    @txn
    def katana_caps(batch, ctx):
        ...
"""

from safe_propose.registry import txn

__all__ = ["txn"]

__version__ = "0.1.0"
