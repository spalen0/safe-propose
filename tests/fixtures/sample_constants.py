"""Constants for ctx.const loading tests. Only data names should be picked up."""

import os  # noqa: F401 - a module; the constants loader must ignore it

AMOUNT = 6_000_000
VAULTS = {"og-usdc": "0xCE2b8e464Fc7b5E58710C24b7e5EBFB6027f29D7"}
MARKET = "0xcdaf57d98c2f75bffb8f0d3f7aa79bbacda4a479c47e316aab14af1ca6d85ffc"

_PRIVATE = "should-be-skipped"


def helper():  # a callable — must be ignored
    return AMOUNT
