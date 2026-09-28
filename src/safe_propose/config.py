"""Resolve everything the engine needs for a given ``--network``.

Precedence (highest first), per ``docs/ARCHITECTURE.md``:

    CLI flag  →  env var  →  consuming ape-config.yaml  →  built-in default

The result is a typed :class:`Config`. Required-but-missing values fail fast with an
actionable message (naming the env var to set). Secrets are stored but never printed:
:class:`Config` has a redacting ``repr``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import yaml

DEFAULT_SAFE_QUEUE_URL = "https://app.safe.global/transactions/queue"

# RPC / HTTP libraries often echo the configured endpoint, including keys in the
# hostname, path, query, or userinfo. Match http(s) and websocket URLs in error text.
_ERROR_URL_RE = re.compile(r"(?i)\b(?:https?|wss?)://[^\s'\"<>\\]+")
_MIN_SECRET_LEN = 8
_SECRET_ENV_NAMES = frozenset(
    {
        "PROPOSER_PRIVATE_KEY",
        "APE_SAFE_GATEWAY_API_KEY",
        "TELEGRAM_TOKEN",
        # Required by the consuming-repo workflow while this repository is private.
        "SAFE_PROPOSE_TOKEN",
    }
)
_SECRET_ENV_SUFFIXES = ("_RPC", "_TX_SERVICE_URL", "SCAN_TOKEN")


def _secret_fragments(value: str, *, include_host: bool = True) -> list[str]:
    """Full secret plus URL userinfo, optional host, path segments, and query values."""
    if not value:
        return []
    out: list[str] = [value] if len(value) >= _MIN_SECRET_LEN else []
    try:
        parsed = urlsplit(value)
    except ValueError:
        return out
    if parsed.password:
        out.append(parsed.password)
    if parsed.username:
        out.append(parsed.username)
    # Full hostname only — not individual labels like ``hyperliquid`` / ``llamarpc``,
    # which otherwise mangled revert text and function names. Tx-service hosts are
    # operator-visible leftovers, not credentials, so callers skip them.
    if include_host and parsed.hostname and len(parsed.hostname) >= _MIN_SECRET_LEN:
        out.append(parsed.hostname)
    out.extend(part for part in parsed.path.split("/") if len(part) >= _MIN_SECRET_LEN)
    if parsed.query:
        out.extend(
            v
            for _, v in parse_qsl(parsed.query, keep_blank_values=True)
            if len(v) >= _MIN_SECRET_LEN
        )
    return out


def _secrets_from_env(env: Mapping[str, str] | None = None) -> list[str]:
    """Collect configured RPC/key values so split host/path errors can be redacted."""
    env = os.environ if env is None else env
    out: list[str] = []
    for name, value in env.items():
        if name in _SECRET_ENV_NAMES or name.endswith(_SECRET_ENV_SUFFIXES):
            include_host = not name.endswith("_TX_SERVICE_URL")
            out.extend(_secret_fragments(value, include_host=include_host))
    return out


def redact_error_text(
    text: str,
    secrets: Iterable[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Strip configured secrets and credential-bearing URLs before printing or posting.

    urllib3/web3 often split an RPC URL into ``host='…'`` and ``url: /<key>/``, which a
    scheme-only regex misses. Replace known secret fragments first (longest first), then
    any remaining http(s)/ws(s) URLs.
    """
    fragments = [*(secrets or []), *_secrets_from_env(env)]
    cleaned = text
    for frag in sorted({f for f in fragments if len(f) >= _MIN_SECRET_LEN}, key=len, reverse=True):
        cleaned = cleaned.replace(frag, "***")
    return _ERROR_URL_RE.sub("***url***", cleaned)


def format_queue_url(base_url: str, safe_shortname: str, safe_address: str) -> str:
    """Build a Safe web queue URL for apps that use the standard ``safe=prefix:addr`` param."""
    sep = "&" if "?" in base_url else "?"
    safe = quote(f"{safe_shortname}:{safe_address}", safe=":")
    return f"{base_url}{sep}safe={safe}"


@dataclass(frozen=True)
class NetworkSpec:
    """Static facts about a supported network."""

    name: str  # canonical name
    chain_id: int
    env_prefix: str  # e.g. "KATANA" → KATANA_SAFE_ADDRESS, KATANA_RPC
    safe_shortname: str  # Safe queue URL prefix, e.g. "katana" → safe=katana:0x..
    safe_queue_url: str = DEFAULT_SAFE_QUEUE_URL


# Built-in knowledge. Chain ids / EIP-3770 shortnames are public constants, not per-safe
# data, so they're allowed here (the engine stays free of safe addresses / market ids).
# Every network connects via the `node` provider with an explicit `<PREFIX>_RPC`
# (declared in the consuming ape-config.yaml; `ethereum:mainnet` is a core Ape network).
# The shortname is the EIP-3770 chain prefix used for the app.safe.global queue link
# (`?safe=<shortname>:<address>`). It is not used to build the tx-service URL: the Safe
# gateway's slug can differ (HyperEVM `hyper-evm` → `hyper`), so txservice.GATEWAY_SLUGS
# maps chain id → slug explicitly.
NETWORK_SPECS: dict[str, NetworkSpec] = {
    "ethereum": NetworkSpec("ethereum", 1, "ETH", "eth"),
    "base": NetworkSpec("base", 8453, "BASE", "base"),
    "arbitrum": NetworkSpec("arbitrum", 42161, "ARB", "arb1"),
    "optimism": NetworkSpec("optimism", 10, "OP", "oeth"),
    "hyperevm": NetworkSpec("hyperevm", 999, "HYPEREVM", "hyper-evm"),
    "katana": NetworkSpec("katana", 747474, "KATANA", "katana"),
    "rise": NetworkSpec(
        "rise",
        4153,
        "RISE",
        "rise",
        safe_queue_url="https://multisig.risechain.com/home",
    ),
    "robinhood": NetworkSpec("robinhood", 4663, "ROBINHOOD", "robinhood"),
}

# Friendly aliases accepted on the CLI.
NETWORK_ALIASES: dict[str, str] = {
    "eth": "ethereum",
    "mainnet": "ethereum",
    "arb": "arbitrum",
    "op": "optimism",
    "hyper": "hyperevm",
    "hyperliquid": "hyperevm",
    "robinhoodchain": "robinhood",
}


class ConfigError(ValueError):
    """Raised when a required configuration value is missing or invalid."""


def normalize_network(network: str) -> str:
    """Map an alias to its canonical network name (or return it unchanged)."""
    key = network.strip().lower()
    return NETWORK_ALIASES.get(key, key)


@dataclass(frozen=True)
class Config:
    """Fully resolved engine configuration for one network.

    Secret fields (``proposer_private_key``, ``gateway_api_key``,
    ``rpc_uri``, ``tx_service_url``) are fully redacted in ``repr`` so credentials
    in URL hostnames, paths, queries, or userinfo cannot be logged.
    """

    network: str
    chain_id: int
    safe_address: str
    safe_shortname: str
    env_prefix: str  # e.g. "KATANA" → the {PREFIX}_RPC env var ape-config interpolates
    rpc_uri: str | None
    proposer_account: str | None  # Ape keyfile account name, if used
    proposer_private_key: str | None  # delegate key from env, if used
    gateway_api_key: str | None
    tx_service_url: str | None  # explicit Safe Tx Service override (e.g. a chain off the gateway)
    safe_queue_url: str  # Safe web URL that accepts ?safe=<shortname>:<address>
    request_timeout: float
    safe_address_fallback: bool = False  # True when ETH_SAFE_ADDRESS stood in for this chain

    _SECRET_FIELDS = (
        "proposer_private_key",
        "gateway_api_key",
        "rpc_uri",
        "tx_service_url",
    )

    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            value = getattr(self, f.name)
            if f.name in self._SECRET_FIELDS:
                value = "***set***" if value else None
            parts.append(f"{f.name}={value!r}")
        return f"Config({', '.join(parts)})"

    @property
    def queue_url(self) -> str:
        """The Safe web queue link for this Safe on this network."""
        return format_queue_url(self.safe_queue_url, self.safe_shortname, self.safe_address)


def _load_ape_config(ape_config_path: str | Path | None) -> dict[str, Any]:
    """Parse the consuming repo's ape-config.yaml, or return {} if absent."""
    if ape_config_path is None:
        return {}
    p = Path(ape_config_path).expanduser()
    if not p.is_file():
        return {}
    with p.open() as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _custom_chain_id(ape_config: dict[str, Any], network: str) -> int | None:
    """Find a custom network's chain id by ecosystem name in ape-config.yaml."""
    custom = (ape_config.get("networks") or {}).get("custom") or []
    for entry in custom:
        if isinstance(entry, dict) and entry.get("ecosystem") == network:
            cid = entry.get("chain_id")
            if isinstance(cid, int):
                return cid
    return None


def resolve_config(
    network: str,
    *,
    cli: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    ape_config_path: str | Path | None = "ape-config.yaml",
) -> Config:
    """Resolve a :class:`Config` for ``network`` using the documented precedence.

    Args:
        network: requested network name or alias.
        cli: explicit CLI overrides (e.g. ``{"safe_address": "0x..", "rpc_uri": ".."}``).
        env: environment mapping (defaults to ``os.environ``).
        ape_config_path: path to the consuming repo's ape-config.yaml.
    """
    cli = cli or {}
    env = env if env is not None else dict(os.environ)
    canonical = normalize_network(network)

    spec = NETWORK_SPECS.get(canonical)
    ape_config = _load_ape_config(ape_config_path)

    # chain id: built-in spec, else custom network in ape-config.
    if spec is not None:
        chain_id = spec.chain_id
        env_prefix = spec.env_prefix
        safe_shortname = spec.safe_shortname
        default_safe_queue_url = spec.safe_queue_url
    else:
        chain_id = _custom_chain_id(ape_config, canonical)
        if chain_id is None:
            known = ", ".join(sorted(NETWORK_SPECS) + sorted(NETWORK_ALIASES))
            raise ConfigError(
                f"unknown network {network!r}. Known: {known}. "
                "For a custom chain, declare it under networks.custom in ape-config.yaml."
            )
        env_prefix = canonical.upper()
        safe_shortname = canonical
        default_safe_queue_url = DEFAULT_SAFE_QUEUE_URL

    def pick(cli_key: str, *env_keys: str) -> str | None:
        if cli.get(cli_key):
            return str(cli[cli_key])
        for k in env_keys:
            if env.get(k):
                return env[k]
        return None

    # Safe address — required. Falls back to the Ethereum-mainnet Safe (ETH_SAFE_ADDRESS)
    # when no per-chain <PREFIX>_SAFE_ADDRESS is set, so one address can cover every chain
    # (a Safe deployed at the same address on all networks) without per-chain config.
    # The fallback is flagged so the CLI can warn: a new chain's Safe is often elsewhere.
    safe_address = pick("safe_address", f"{env_prefix}_SAFE_ADDRESS")
    safe_address_fallback = False
    if not safe_address and env_prefix != "ETH" and env.get("ETH_SAFE_ADDRESS"):
        safe_address = env["ETH_SAFE_ADDRESS"]
        safe_address_fallback = True
    if not safe_address:
        raise ConfigError(
            f"no Safe address for {canonical}; set {env_prefix}_SAFE_ADDRESS "
            "(or ETH_SAFE_ADDRESS as a fallback) or pass --safe-address."
        )

    # RPC URI — required: every network connects via the `node` provider with this URI
    # (declared in the consuming ape-config as ${<PREFIX>_RPC}).
    rpc_uri = pick("rpc_uri", f"{env_prefix}_RPC")
    if rpc_uri is None:
        raise ConfigError(f"no RPC for {canonical}; set {env_prefix}_RPC or pass --rpc-uri.")

    # Proposer: a keyfile account name OR a raw delegate key from env.
    proposer_account = pick("proposer_account", "PROPOSER_ACCOUNT")
    proposer_private_key = env.get("PROPOSER_PRIVATE_KEY") or None

    gateway_api_key = env.get("APE_SAFE_GATEWAY_API_KEY") or None
    # Explicit Safe Tx Service override for chains not on the unified gateway (e.g.
    # HyperEVM): per-chain `<PREFIX>_TX_SERVICE_URL`, else a global `SAFE_TX_SERVICE_URL`.
    tx_service_url = pick("tx_service_url", f"{env_prefix}_TX_SERVICE_URL", "SAFE_TX_SERVICE_URL")
    safe_queue_url = (
        pick("safe_queue_url", f"{env_prefix}_SAFE_QUEUE_URL", "SAFE_QUEUE_URL")
        or default_safe_queue_url
    )

    timeout_raw = cli.get("request_timeout") or env.get("SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT")
    try:
        request_timeout = float(timeout_raw) if timeout_raw else 10.0
    except (TypeError, ValueError):
        raise ConfigError(
            f"SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT must be a number (got {timeout_raw!r})."
        ) from None

    return Config(
        network=canonical,
        chain_id=chain_id,
        safe_address=safe_address,
        safe_shortname=safe_shortname,
        env_prefix=env_prefix,
        rpc_uri=rpc_uri,
        proposer_account=proposer_account,
        proposer_private_key=proposer_private_key,
        tx_service_url=tx_service_url,
        safe_queue_url=safe_queue_url,
        gateway_api_key=gateway_api_key,
        request_timeout=request_timeout,
        safe_address_fallback=safe_address_fallback,
    )
