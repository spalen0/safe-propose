"""Ape connection + Safe loading orchestration (the network glue).

This is the layer between ``config``/``loader`` (pure) and ``engine`` (needs a connected
``SafeAccount`` + ``Ctx``). It encapsulates what the Katana spike proved is required:

  * connect Ape to the target network — a **fork** (foundry/anvil) for ``dry-run``
    simulation, or the **live** node for ``send``;
  * register/load the Safe by address under a stable alias (no manual ``ape safe add``);
  * on explorer-less chains (e.g. Katana) inject the bundled Safe ABI at the proxy **and**
    its fallback-handler address, so on-chain reads (nonce, owners) resolve;
  * build the ``Ctx`` with a contract factory for tx definitions.

Ape and ape-safe are imported lazily inside functions so the rest of the package (and the
offline unit suite) never need a network or the heavy stack at import time.
"""

from __future__ import annotations

import contextlib
import os
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from safe_propose.config import Config
from safe_propose.context import Ctx, make_const

# Safe contract version whose bundled ABI we inject on explorer-less chains. ape-safe
# ships 1.3.0 and 1.4.1; nonce()/getOwners()/execTransaction selectors are identical
# across them, so 1.4.1 reads work even against a 1.3.0 deployment.
DEFAULT_SAFE_ABI_VERSION = "1.4.1"


def safe_alias(config: Config) -> str:
    """Stable local alias for the target Safe (per network + address)."""
    return f"sp-{config.network}-{config.safe_address[:10].lower()}"


def network_choice(config: Config, *, fork: bool, net_name: str = "mainnet") -> str:
    """Build the Ape network-choice string.

    Fork (simulation): ``<ecosystem>:<net>-fork:foundry``.
    Live (propose):    ``<ecosystem>:<net>:node``.

    The ecosystem/network must be declared in the consuming repo's ape-config.yaml
    (custom networks like Katana); ``node`` reads its URI from that config / env.
    """
    eco = config.network
    if fork:
        return f"{eco}:{net_name}-fork:foundry"
    return f"{eco}:{net_name}:node"


def ensure_safe_registered(config: Config) -> str:
    """Write the ape-safe account file for the target Safe if absent; return its alias.

    Avoids the explorer-dependent ``ape safe add`` (which fails on Katana). The file
    format is ape-safe's own: ``{"address", "deployed_chain_ids"}``.
    """
    import json

    alias = safe_alias(config)
    data_folder = Path(os.environ.get("APE_DATA_FOLDER", Path.home() / ".ape"))
    safe_dir = data_folder / "safe"
    safe_dir.mkdir(parents=True, exist_ok=True)
    path = safe_dir / f"{alias}.json"
    if not path.is_file():
        path.write_text(
            json.dumps({"address": config.safe_address, "deployed_chain_ids": [config.chain_id]})
        )
    return alias


def inject_safe_abi(safe: Any, *, version: str = DEFAULT_SAFE_ABI_VERSION) -> str | None:
    """Cache the bundled Safe ABI at the proxy + fallback-handler addresses.

    Needed on chains with no ape-etherscan explorer (Katana): without it, ``safe.contract``
    and nonce reads raise ``ContractNotFoundError``. Returns the fallback-handler address
    (for logging), or ``None`` if it could not be read. Best-effort: if an explorer is
    available this is harmless.
    """
    from ape import chain
    from ape_safe.packages import PackageType
    from eth_utils import keccak

    safe_type = PackageType.SINGLETON(version).contract_type
    chain.contracts.cache_contract_type(safe.address, safe_type)

    try:
        slot = keccak(text="fallback_manager.handler.address")
        raw = chain.provider.get_storage(safe.address, slot)
        fb = chain.provider.network.ecosystem.decode_address(raw[-20:])
        if int(fb, 16) != 0:
            chain.contracts.cache_contract_type(fb, safe_type)
            return fb
    except Exception:
        return None
    return None


def safe_onchain_nonce(safe: Any) -> int:
    """Read the Safe contract's current nonce (the next executable SafeTx nonce).

    Must not use ``safe.nonce`` or ``Contract(address).nonce``: Ape's ``AccountAPI.nonce``
    (the EOA transaction count) shadows the Safe getter. A Safe that has never sent as an
    EOA always reports 0, which made dry-run previews hash nonce 0. ape-safe documents
    this and reads the getter via ``contract._view_methods_["nonce"]``.
    """
    try:
        return int(safe.contract._view_methods_["nonce"]())
    except Exception as exc:
        raise RuntimeError(
            f"could not read the Safe on-chain nonce ({exc}); aborting so we don't "
            "preview a SafeTx at a guessed nonce."
        ) from exc


def _contract_factory() -> Any:
    """Return a ``ctx.contract`` factory backed by Ape's ``Contract``.

    Method handlers gain a 4-byte ``.selector`` (see :mod:`safe_propose.selectors`);
    the returned object is Ape's own ``ContractInstance``.
    """
    from ape import Contract

    from safe_propose.selectors import install_method_selector

    install_method_selector()

    def factory(address: str, abi: Any = None) -> Any:
        return Contract(address, abi=abi, fetch_from_explorer=abi is None)

    return factory


def make_ctx(config: Config, const: dict[str, Any] | None = None) -> Ctx:
    """Build the ``Ctx`` handed to tx definitions for this run."""
    return Ctx(
        network=config.network,
        chain_id=config.chain_id,
        safe_address=config.safe_address,
        const=make_const(const),
        _contract=_contract_factory(),
    )


def import_key_account(alias: str, private_key: str) -> Any:
    """Import a raw private key into a fresh ephemeral keyfile and enable autosign.

    Returns an Ape account that signs non-interactively for this session. The key is
    never logged. Used by ``load_proposer`` and by standalone scripts that need a signer
    without a full :class:`Config` (e.g. deploying a test Safe before one exists).
    """
    import secrets

    from ape_accounts.accounts import import_account_from_private_key

    passphrase = secrets.token_hex(16)
    # Always re-import under a fresh passphrase: a keyfile left by a prior run would have a
    # different passphrase, so reusing it would break the autosign unlock (the account would
    # fall back to an interactive prompt). The ephemeral keyfile is ours to overwrite.
    data_folder = Path(os.environ.get("APE_DATA_FOLDER", Path.home() / ".ape"))
    keyfile = data_folder / "accounts" / f"{alias}.json"
    if keyfile.exists():
        keyfile.unlink()

    acct = import_account_from_private_key(alias, passphrase, private_key)
    acct.set_autosign(True, passphrase=passphrase)
    return acct


def load_proposer(config: Config) -> Any:
    """Load the delegate/proposer account for ``send``.

    Prefers an Ape keyfile account (``config.proposer_account`` / ``PROPOSER_ACCOUNT``).
    Otherwise imports the raw ``PROPOSER_PRIVATE_KEY`` (autosign). Raises ``ConfigError``
    if no proposer is configured.
    """
    from ape import accounts

    from safe_propose.config import ConfigError

    if config.proposer_account:
        return accounts.load(config.proposer_account)

    key = config.proposer_private_key
    if not key:
        raise ConfigError("no proposer configured; set PROPOSER_PRIVATE_KEY or PROPOSER_ACCOUNT.")
    return import_key_account(f"{safe_alias(config)}-proposer", key)


def _inject_tx_service_client(safe: Any, endpoint: Any) -> None:
    """Point the Safe's (cached) client at the resolved Tx Service endpoint.

    The resolved ``base_url`` is always passed as ``override_url``: ape-safe's own chain map
    does not know several chains we support (Katana raises "not a supported chain", and
    HyperEVM/Robinhood use gateway slugs it cannot derive), and the service we printed must
    be the one we call. The resolved timeout is wired in via
    ``SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT`` (the env var safe-eth-py reads at client
    construction), so the client is never left on an untimed default — the whole point of
    this repo.
    """
    timeout = getattr(endpoint, "timeout", None)
    if timeout:
        os.environ["SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT"] = str(timeout)
    client = safe.get_client(chain_id=safe.chain_manager.chain_id, override_url=endpoint.base_url)
    if not getattr(endpoint, "is_safe_gateway", False):
        _drop_gateway_auth(client)
    safe.__dict__["client"] = client


def _drop_gateway_auth(client: Any) -> None:
    """Stop ape-safe sending ``APE_SAFE_GATEWAY_API_KEY`` to a non-Safe host.

    ``SafeClient._request`` adds ``Authorization: Bearer <key>`` on every request whatever
    the base URL, which would hand the Safe key to RISE's service or any operator-supplied
    ``*_TX_SERVICE_URL``. Bypass it with the header-free ``RequestsClient._request``.
    """
    from ape_safe.client import SafeClient
    from ape_safe.client.base import RequestsClient

    if isinstance(client, SafeClient):
        client._request = types.MethodType(RequestsClient._request, client)


def proposal_nonce(safe: Any, endpoint: Any) -> int:
    """Next nonce for a new proposal, **queue-aware** (accounts for pending txs).

    Reads it from the Tx Service via the resolved endpoint (ape-safe's ``new_nonce``).
    **Fails closed**: if the service is unreachable we raise rather than fall back to the
    on-chain nonce, because guessing the on-chain nonce while queued-but-unexecuted txs
    exist would propose a *conflicting* tx at an already-used nonce. The caller (``send``)
    aborts; retry when the service is reachable.
    """
    _inject_tx_service_client(safe, endpoint)
    try:
        return int(safe.new_nonce)
    except Exception as exc:
        raise RuntimeError(
            f"could not read the Safe Tx Service nonce ({exc}); aborting so we don't "
            "propose a conflicting nonce. Retry when the service is reachable."
        ) from exc


def propose(safe: Any, safe_tx: Any, endpoint: Any, submitter: Any) -> str:
    """Propose ``safe_tx`` to the Safe Tx Service, honouring an override URL.

    Injects a client built for the resolved endpoint and posts via ``propose_safe_tx``.
    Returns the ``safe_tx_hash``. The HTTP call is time-bounded by the endpoint's
    client kwargs.
    """
    _inject_tx_service_client(safe, endpoint)
    return str(safe.propose_safe_tx(safe_tx, submitter=submitter))


@contextlib.contextmanager
def connect(config: Config, *, fork: bool, net_name: str = "mainnet") -> Iterator[Any]:
    """Connect Ape to the target network and yield a loaded, ABI-injected ``SafeAccount``.

    ``fork=True`` runs against a foundry fork (for ``dry-run`` simulation); ``fork=False``
    connects to the live node (for ``send``). The Safe is registered + loaded and its ABI
    injected for explorer-less chains before yielding.
    """
    from ape import accounts, networks

    # Honour a CLI/config RPC override: the consuming ape-config interpolates
    # ${<PREFIX>_RPC}, so setting it here makes --rpc-uri actually take effect for
    # both the live `node` provider and the foundry fork's upstream (the operator's
    # "switch RPC to avoid a hang" path).
    if config.rpc_uri:
        os.environ[f"{config.env_prefix}_RPC"] = config.rpc_uri

    alias = ensure_safe_registered(config)
    choice = network_choice(config, fork=fork, net_name=net_name)
    with networks.parse_network_choice(choice):
        safe = accounts.load(alias)
        inject_safe_abi(safe)
        yield safe
