"""Resolve the Safe Transaction Service endpoint and guarantee a timeout.

This is the module most directly tied to the incident this repo exists to prevent: a
no-timeout external call in an EOL stack hung a Katana run for ~15 minutes. Here, every
resolved endpoint carries an explicit timeout, and selecting the gateway without an API
key is a hard, immediate error rather than a silent attempt that stalls.

Two paths:
  * **gateway** (default): ``https://api.safe.global/tx-service/{slug}/api`` with
    ``APE_SAFE_GATEWAY_API_KEY`` as a Bearer token. The slug is Safe's per-chain service
    name, which is not always the EIP-3770 queue prefix (HyperEVM, Robinhood).
  * **override** (fallback / explicit): a per-chain standalone service, e.g. Katana →
    ``https://safe-transaction-katana.safe.global`` (keyless). The gateway key is only
    sent to the Safe gateway host, never to an override on another host.
"""

from __future__ import annotations

from dataclasses import dataclass

SAFE_GATEWAY_HOST = "api.safe.global"
GATEWAY_TEMPLATE = f"https://{SAFE_GATEWAY_HOST}/tx-service/{{slug}}/api"

# Chains the unified Safe gateway serves, keyed by chain id → the gateway's tx-service
# slug. The slug usually equals the EIP-3770 queue prefix but not always (HyperEVM's prefix
# is `hyper-evm`, its slug `hyper`), so it is listed here rather than
# derived from the network's shortname. Other chains need a standalone override
# (OVERRIDE_URLS) or an explicit `override_url`.
GATEWAY_SLUGS: dict[int, str] = {
    1: "eth",  # ethereum
    8453: "base",  # base
    42161: "arb1",  # arbitrum
    10: "oeth",  # optimism
    999: "hyper",  # hyperevm
    4663: "robinhood",  # robinhood chain
}

# Per-chain standalone Tx Service URLs, off the Safe gateway. Keyed by chain id.
# IMPORTANT: the base **must end in `/api`** — ape-safe's SafeClient appends endpoint
# paths (`/v1/safes/…`, `/v2/delegates`) directly to base_url, exactly as it does for the
# gateway base (`{gateway}/{slug}/api`). Omitting `/api` makes those calls 404.
OVERRIDE_URLS: dict[int, str] = {
    4153: "https://multisig-txs.risechain.com/api",
    747474: "https://safe-transaction-katana.safe.global/api",
}

DEFAULT_TIMEOUT = 10.0


class TxServiceError(ValueError):
    """Raised when the Tx Service endpoint cannot be resolved safely."""


@dataclass(frozen=True)
class TxServiceEndpoint:
    """A resolved, timeout-bearing Tx Service endpoint.

    ``timeout`` is never ``None`` by construction — that is the whole point.
    """

    base_url: str
    timeout: float
    is_override: bool

    def __post_init__(self) -> None:
        if self.timeout is None or self.timeout <= 0:
            raise TxServiceError(
                "Tx Service endpoint requires a positive timeout (no untimed calls)."
            )

    def public_origin(self) -> str:
        """``scheme://host`` with credentials stripped, for operator confirmation.

        The host is shown even when ``SAFE_TX_SERVICE_URL`` / ``*_TX_SERVICE_URL`` is set
        so leftover overrides are visible. Path and query stay off this string.
        """
        from urllib.parse import urlsplit

        parts = urlsplit(self.base_url)
        if not parts.scheme or not parts.hostname:
            return ""
        return f"{parts.scheme}://{parts.hostname}"

    @property
    def is_safe_gateway(self) -> bool:
        """Whether the endpoint is on the Safe gateway host, the only one sent the API key."""
        from urllib.parse import urlsplit

        parts = urlsplit(self.base_url)
        return parts.scheme == "https" and parts.hostname == SAFE_GATEWAY_HOST

    def __repr__(self) -> str:
        url = "***set***" if self.base_url else None
        return (
            f"TxServiceEndpoint(base_url={url!r}, timeout={self.timeout!r}, "
            f"is_override={self.is_override!r})"
        )


def resolve_endpoint(
    chain_id: int,
    *,
    gateway_api_key: str | None,
    timeout: float = DEFAULT_TIMEOUT,
    override_url: str | None = None,
) -> TxServiceEndpoint:
    """Resolve the Tx Service endpoint for a chain.

    Resolution order:
      1. An explicit ``override_url`` (e.g. from CLI/config) always wins. No key is
         required; the runtime sends the gateway key only if it points at the gateway host.
      2. Otherwise, if the chain has a built-in standalone override, use it (keyless),
         **even when a gateway key is set** — the gateway does not serve these chains, so
         the override is the only path that works.
      3. Otherwise, if the chain is on the gateway (``GATEWAY_SLUGS``), use it — requires
         an API key. The key is not stored on the endpoint; ape-safe reads
         ``APE_SAFE_GATEWAY_API_KEY`` from the environment.
      4. Otherwise the chain has no known Tx Service: raise so the caller supplies an
         ``override_url`` (e.g. ``<PREFIX>_TX_SERVICE_URL``) — never a URL that 404s.

    Raises ``TxServiceError`` if the gateway is selected without an API key, or for a chain
    with no known service and no override.
    """
    if not timeout or timeout <= 0:
        raise TxServiceError(f"timeout must be positive, got {timeout!r}.")

    # 1. explicit override.
    if override_url:
        return TxServiceEndpoint(base_url=override_url, timeout=timeout, is_override=True)

    # 2. built-in standalone override — preferred for chains the gateway can't serve,
    #    regardless of whether a gateway key happens to be configured.
    builtin_override = OVERRIDE_URLS.get(chain_id)
    if builtin_override:
        return TxServiceEndpoint(base_url=builtin_override, timeout=timeout, is_override=True)

    # 3./4. gateway — only for chains it actually serves.
    slug = GATEWAY_SLUGS.get(chain_id)
    if slug is None:
        raise TxServiceError(
            f"no Safe Tx Service known for chain {chain_id}. The unified gateway does not "
            "serve it and there is no built-in override. Provide one via "
            f"<PREFIX>_TX_SERVICE_URL / SAFE_TX_SERVICE_URL (a base URL ending in /api)."
        )
    if not gateway_api_key:
        raise TxServiceError(
            f"Safe gateway selected for chain {chain_id} but APE_SAFE_GATEWAY_API_KEY is not set."
        )
    return TxServiceEndpoint(
        base_url=GATEWAY_TEMPLATE.format(slug=slug),
        timeout=timeout,
        is_override=False,
    )
