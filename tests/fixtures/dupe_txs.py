"""A tx module that registers the same name twice — must raise on import."""

from safe_propose import txn


@txn
def alpha(batch, ctx):
    pass


@txn
def alpha(batch, ctx):  # noqa: F811 - intentional duplicate for the test
    pass
