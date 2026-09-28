"""A minimal tx-definition module used by loader tests (not a real safe)."""

from safe_propose import txn


@txn
def alpha(batch, ctx):
    batch.add("alpha-call", ctx.chain_id)


@txn
def beta(batch, ctx):
    batch.add("beta-call", ctx.const["amount"])
