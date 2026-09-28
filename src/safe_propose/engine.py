"""Build an ape-safe batch from a tx definition and simulate it.

The output is a pure-data :class:`SimulationResult` (no Ape objects) so that
``render.py`` and the test suite can consume it without a network connection. The
network-touching steps (``build``/``simulate``) are isolated here and exercised by the
Layer-2 forked-chain integration tests (marked ``live``).

Design decision (Task 04): tx definitions queue calls with ``batch.add(method, *args)``
— explicit, deterministic encoding straight from the ABI. We do *not* default to
``batch.add_from_receipt`` (simulate-then-record): the definitions already carry decoded
arguments, so ``add`` avoids an extra impersonated execution per call and keeps the
``safe_tx_hash`` a pure function of (calls, nonce). Recorded in ``docs/ARCHITECTURE.md``.

ape-safe API used here (verified against ape-safe 0.8.23, Task 02a/04 spike):
  * ``safe.create_batch()`` → ``MultiSend``
  * ``batch.add(method, *args, value=0)``
  * ``safe.safe_tx_def(...)`` + ``ape_safe.utils.get_safe_tx_hash`` → EIP-712 SafeTx
    (not ``batch.as_safe_tx`` / ``as_transaction``, which eagerly call ``new_nonce``)
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from safe_propose.config import redact_error_text


def _to_hex(value: Any) -> str:
    """Normalize bytes / HexBytes / str to a 0x-prefixed lowercase hex string."""
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    if isinstance(value, bytes | bytearray):
        return "0x" + bytes(value).hex()
    return str(value)


@dataclass(frozen=True)
class DecodedCall:
    """One decoded call within the Safe batch (for human-readable diff/output)."""

    target: str
    function: str  # 4-byte selector, e.g. 0x095ea7b3
    args: tuple[Any, ...]
    value: int = 0
    data: str = ""  # full calldata hex for this inner call (signer verification)


@dataclass(frozen=True)
class CallSim:
    """One inner call's simulation result, brownie-style (``Contract.method → ok, gas≈N``).

    ``contract_name``/``method``/``args`` are best-effort, decoded from the cached ABI;
    when the ABI is unavailable they fall back to ``""``/the 4-byte selector/``()`` so the
    trace still renders (see :func:`simulate_trace`). ``gas`` is ``None`` when the estimate
    could not be obtained (e.g. the call reverts).
    """

    index: int  # 1-based position in the batch
    target: str
    contract_name: str  # "" if the ABI is unknown
    method: str  # method name, or the 4-byte selector when undecodable
    args: tuple[Any, ...]
    value: int = 0
    success: bool = True
    gas: int | None = None
    revert_reason: str = ""  # "" when success
    error: str = ""  # RPC / transport failures, distinct from contract reverts
    gas_error: str = ""  # gas estimation is advisory after a successful eth_call

    @property
    def label(self) -> str:
        """``Contract.method`` (or just ``method``/selector when the contract is unknown)."""
        prefix = f"{self.contract_name}." if self.contract_name else ""
        return f"{prefix}{self.method}"


@dataclass(frozen=True)
class SimulationResult:
    """Structured result of building + simulating a Safe transaction.

    Pure data: safe to snapshot-test and to hand to ``render.py``.
    """

    fn_name: str
    network: str
    chain_id: int
    safe_address: str
    safe_shortname: str
    nonce: int
    safe_tx_hash: str
    decoded_calls: tuple[DecodedCall, ...]
    # Per-call simulation trace (Contract.method + estimated gas + ok/revert). Empty when
    # the dry-run was run with --no-execute (no simulation performed).
    call_sims: tuple[CallSim, ...] = field(default_factory=tuple)
    # The full EIP-712 SafeTx message a wallet shows when signing (see safe_tx_fields).
    tx_fields: dict[str, Any] = field(default_factory=dict)
    traces: tuple[str, ...] = field(default_factory=tuple)
    success: bool = True


def build(fn: Any, ctx: Any, safe: Any) -> Any:
    """Create a fresh ape-safe batch and run the tx definition against it.

    ``safe`` is a connected ape-safe ``SafeAccount``. Returns the populated ``MultiSend``.
    """
    batch = safe.create_batch()
    fn(batch, ctx)
    return batch


def decode_calls(batch: Any) -> tuple[DecodedCall, ...]:
    """Decode a built batch into :class:`DecodedCall` rows for human-readable output.

    ape-safe's ``MultiSend`` tracks queued calls in ``batch.calls`` as dicts of
    ``{"target", "value", "callData"}``. We surface target/value and the 4-byte selector;
    full argument decoding (selector → name + args) is left to ``render.py`` where the
    ABI is available. Falls back to an empty tuple rather than crashing the render.
    """
    out: list[DecodedCall] = []
    for c in getattr(batch, "calls", None) or []:
        data = c.get("callData", b"") if isinstance(c, dict) else b""
        selector = "0x" + bytes(data)[:4].hex() if data else ""
        target = c.get("target", "") if isinstance(c, dict) else ""
        value = c.get("value", 0) if isinstance(c, dict) else 0
        out.append(
            DecodedCall(
                target=str(target),
                function=selector,
                args=(),
                value=int(value or 0),
                data=_to_hex(data),
            )
        )
    return tuple(out)


def safe_tx_fields(safe_tx: Any) -> dict[str, Any]:
    """Extract the full EIP-712 SafeTx message — exactly what a wallet shows when signing.

    All ten fields the Safe UI / MetaMask display for the typed-data signature, so a signer
    can compare field-by-field. ``data`` is the full inner (MultiSend) calldata.
    """
    return {
        "to": str(safe_tx.to),
        "value": int(safe_tx.value),
        "data": _to_hex(safe_tx.data),
        "operation": int(safe_tx.operation),
        "safeTxGas": int(safe_tx.safeTxGas),
        "baseGas": int(safe_tx.baseGas),
        "gasPrice": int(safe_tx.gasPrice),
        "gasToken": str(safe_tx.gasToken),
        "refundReceiver": str(safe_tx.refundReceiver),
        "nonce": int(safe_tx.nonce),
    }


def build_safe_tx(batch: Any, safe: Any, *, nonce: int | None = None) -> tuple[Any, str, int]:
    """Return ``(safe_tx, safe_tx_hash, nonce)`` for a built batch.

    Pure (no execution): builds the EIP-712 SafeTx and its canonical hash. The hash is a
    deterministic function of the calls and the Safe nonce.

    We do **not** use ``batch.as_safe_tx`` / ``safe.create_safe_tx``: in ape-safe 0.8.x
    those compute the nonce as ``safe_tx_kwargs.get("nonce", self.new_nonce)``, and Python
    eagerly evaluates ``self.new_nonce`` — a Safe Tx Service call — *even when an explicit
    nonce is passed*. On a chain the bundled ``SafeClient`` does not know (e.g. Katana /
    747474) that raises "not a supported chain", so a batch could not be built offline at
    all. Instead we assemble the EIP-712 ``SafeTx`` directly from ``safe.safe_tx_def`` with
    an explicit nonce — fully decoupled from the Tx Service. (Queued-aware "next nonce"
    that accounts for already-pending txs is a ``send``-path concern handled via the
    ``txservice`` override URL; see ``docs/ARCHITECTURE.md`` Task 02b.)

    ``nonce`` must be supplied for service-unsupported chains. If ``None``, we fall back to
    ape-safe's ``new_nonce`` (which requires a supported Tx Service).
    """
    from ape.utils import ZERO_ADDRESS
    from ape_safe.client.types import OperationType
    from ape_safe.utils import get_safe_tx_hash

    if nonce is None:
        nonce = int(safe.new_nonce)  # service-backed; only valid on supported chains

    # Mirror MultiSend.as_safe_tx: the batch is executed via DELEGATECALL to the
    # MultiSend(CallOnly) contract with the concatenated, encoded calls as data.
    to = batch.contract.address
    data = batch.handler.encode_input(b"".join(batch.encoded_calls))

    safe_tx = safe.safe_tx_def(
        to=to,
        value=0,
        data=data,
        operation=OperationType.DELEGATECALL,
        nonce=int(nonce),
        safeTxGas=0,
        gasPrice=0,
        gasToken=ZERO_ADDRESS,
        refundReceiver=ZERO_ADDRESS,
    )
    safe_tx_hash = str(get_safe_tx_hash(safe_tx))
    return safe_tx, safe_tx_hash, int(safe_tx.nonce)


def execute_safe_tx(safe: Any, safe_tx: Any, *, signers: list[Any], submitter: Any = None) -> Any:
    """Sign ``safe_tx`` with ``signers`` and execute it on-chain (service-free).

    This is the local/MVP execution path: real owner signatures (no impersonation, no Tx
    Service), so it works on any chain — including those the bundled ``SafeClient`` does
    not know (Katana). ``signers`` must cover the Safe's threshold; ``submitter`` (default
    the first signer) pays gas. Returns the Ape receipt. Intended for a node/fork where the
    caller controls the owner keys; production multi-owner flows propose instead (``send``).
    """
    submitter = submitter or signers[0]
    sigs: dict = {}
    for signer in signers:
        sig = signer.sign_message(safe_tx)
        if sig is not None:
            sigs[signer.address] = sig
    txn = safe.create_execute_transaction(safe_tx, sigs, submitter=submitter)
    return submitter.call(txn)


def _decode_call_intent(
    target: str, calldata: bytes, *, contract_lookup: Any
) -> tuple[str, str, tuple[Any, ...]]:
    """Best-effort ``(contract_name, method, args)`` for one inner call.

    Uses the already-cached contract ABI (tx definitions resolve every target via
    ``ctx.contract(...)``, so its type is cached in Ape's ``chain.contracts`` — this works
    on explorer-less chains like Katana via the consuming repo's ``interfaces/*.json``).
    Falls back to ``("", <4-byte selector>, ())`` if the ABI is unavailable or the calldata
    cannot be decoded, so the trace never crashes the dry-run.
    """
    selector = "0x" + bytes(calldata)[:4].hex() if calldata else ""
    try:
        contract = contract_lookup(target)
        signature, input_dict = contract.decode_input(bytes(calldata))
        method = signature.split("(", 1)[0]
        name = getattr(getattr(contract, "contract_type", None), "name", "") or ""
        return name, method, tuple(input_dict.values())
    except Exception:
        return "", selector, ()


def simulate_trace(
    batch: Any, safe: Any, *, contract_lookup: Any = None, require_ordered: bool = False
) -> tuple[CallSim, ...]:
    """Per-call simulation trace: ``Contract.method(args) → ok/revert, gas≈N``.

    For each queued call it (a) decodes the contract/method/args from the cached ABI and
    (b) replays the call read-only with ``from = safe.address`` (the caller address, so
    Safe-only methods like a curator ``submitCap`` pass) plus an ``estimate_gas`` —
    capturing success, the estimated gas, and a readable revert reason. No owner signature,
    no impersonated ``execTransaction``, no Tx Service. This is the human-readable parity
    with the roboanimals/brownie per-call trace, and the source of both the dry-run trace
    and ``send``'s pre-flight (a non-empty set of reverting calls aborts the send).

    **Ordered batch state on forks:** a Safe MultiSend runs its calls in order, so a
    ``withdraw`` can fund a later ``transfer``. On a dev node (Anvil/Hardhat fork, detected
    via ``evm_snapshot`` + ``*_impersonateAccount``) each call that passes is *applied* — sent
    from the impersonated Safe at zero base fee — before the next call is checked, and the
    snapshot is reverted when the trace finishes. Failed calls are not applied, and a call
    whose apply fails is reported as failed. Nodes without those RPCs (a live node) fall back
    to checking each call independently against the same pre-state, which can both
    false-reject and miss failures in dependent batches. ``require_ordered=True`` raises
    instead of falling back; ``dry-run`` and ``send`` set it and always run on a fork.
    Calls run from the Safe as ``msg.sender``, not inside a delegatecall ``execTransaction``.

    The Safe is the inner-call *authorization* sender, not the executor paying gas. Some
    RPCs (notably Anvil forks of Katana) still enforce ``balance >= gas * gasPrice`` on
    ``eth_call`` even when ``gasPrice`` is set to 0 — middleware or the node may ignore /
    replace that field. For ``value == 0`` calls we therefore apply a temporary
    ``state_override`` balance on the Safe so gas accounting cannot false-fail; native
    ``value > 0`` transfers still use the real balance. The same top-up is applied via
    ``*_setBalance`` before persisting a passing call, because OP-stack forks can still
    charge operator/L1 fees on ``eth_sendTransaction`` even after zeroing the L2 base
    fee (receipt then never appears). RPC errors fail the pre-flight separately from
    contract reverts; exception text is URL-redacted so an endpoint key is never copied
    into the report. Gas-estimation failures leave ``gas=None`` and an advisory
    diagnostic after a successful call.

    ``contract_lookup`` resolves an address to an Ape contract (with ``decode_input`` and
    ``contract_type``); it defaults to ``ape.Contract`` and is injectable for testing.
    """
    if contract_lookup is None:
        from ape import Contract

        def contract_lookup(address: str) -> Any:
            return Contract(address, fetch_from_explorer=False)

    w3 = safe.provider.web3
    sequential = _begin_sequential(w3, safe.address)
    if sequential is None and require_ordered:
        raise RuntimeError(
            "pre-flight needs a fork that supports evm_snapshot and account impersonation "
            "to simulate calls in batch order; refusing to fall back to independent checks"
        )
    sims: list[CallSim] = []
    try:
        for i, c in enumerate(getattr(batch, "calls", None) or [], start=1):
            if not isinstance(c, dict):
                continue
            target = str(c.get("target", ""))
            calldata = bytes(c.get("callData", b"") or b"")
            value = int(c.get("value", 0) or 0)
            name, method, args = _decode_call_intent(
                target, calldata, contract_lookup=contract_lookup
            )

            tx = {
                "from": safe.address,
                "to": target,
                "data": calldata,
                "value": value,
                "gasPrice": 0,
            }
            outcome = _simulate_call(w3.eth, tx)
            if sequential is not None and outcome.get("success", True):
                apply_error = _apply_call(w3, sequential[1], tx)
                if apply_error:
                    outcome = {**outcome, "success": False, "error": apply_error}
            sims.append(
                CallSim(
                    index=i,
                    target=target,
                    contract_name=name,
                    method=method,
                    args=args,
                    value=value,
                    **outcome,
                )
            )
    finally:
        if sequential is not None:
            _end_sequential(w3, safe.address, *sequential)
    return tuple(sims)


def _rpc(w3: Any, method: str, params: list[Any]) -> Any:
    """Raw JSON-RPC request; raises on an RPC error response."""
    response = w3.provider.make_request(method, params)
    if "error" in response:
        raise RuntimeError(f"{method}: {response['error']}")
    return response.get("result")


def _begin_sequential(w3: Any, safe_address: str) -> tuple[Any, str] | None:
    """Snapshot a dev node and impersonate the Safe; ``(snapshot_id, rpc_prefix)`` or None.

    ``None`` means the node cannot hold batch state (a live node), so calls are checked
    independently. Nothing is ever sent unless impersonation succeeded.
    """
    try:
        snapshot = _rpc(w3, "evm_snapshot", [])
    except Exception:
        return None
    for prefix in ("anvil", "hardhat"):
        try:
            _rpc(w3, f"{prefix}_impersonateAccount", [safe_address])
            return snapshot, prefix
        except Exception:
            continue
    with contextlib.suppress(Exception):
        _rpc(w3, "evm_revert", [snapshot])
    return None


def _apply_call(w3: Any, prefix: str, tx: dict[str, Any]) -> str:
    """Persist a passing call on the fork so later calls see its state; ``""`` on success.

    The next block's base fee is zeroed so the (possibly ETH-less) Safe pays no L2 gas.
    OP-stack forks (Katana) can still charge operator/L1 fees, so ``value == 0`` calls
    also get a temporary ``*_setBalance`` on the impersonated Safe. Native transfers
    still use the real balance. The sequential snapshot restores both afterwards.
    """
    try:
        if int(tx.get("value") or 0) == 0 and tx.get("from"):
            _rpc(w3, f"{prefix}_setBalance", [tx["from"], _SIM_GAS_BALANCE_OVERRIDE])
        _rpc(w3, f"{prefix}_setNextBlockBaseFeePerGas", ["0x0"])
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=_APPLY_TIMEOUT)
    except Exception as exc:
        return f"apply failed: {redact_error_text(str(exc))}"
    if int(receipt["status"]) != 1:
        return "apply failed: transaction reverted when applied to the fork"
    return ""


def _end_sequential(w3: Any, safe_address: str, snapshot: Any, prefix: str) -> None:
    """Stop impersonating and restore the pre-trace fork state (best effort)."""
    with contextlib.suppress(Exception):
        _rpc(w3, f"{prefix}_stopImpersonatingAccount", [safe_address])
    with contextlib.suppress(Exception):
        _rpc(w3, "evm_revert", [snapshot])


# Seconds to wait for an applied call's receipt on the (auto-mining) fork.
_APPLY_TIMEOUT = 10


# Enough for any eth_call gas check; not used when the call transfers native value.
_SIM_GAS_BALANCE_OVERRIDE = hex(10**18)


def _gas_balance_override(tx: dict[str, Any]) -> dict[str, Any] | None:
    """State-override so zero-ETH Safes pass gas checks without funding native transfers."""
    if int(tx.get("value") or 0) != 0:
        return None
    sender = tx.get("from")
    if not sender:
        return None
    return {sender: {"balance": _SIM_GAS_BALANCE_OVERRIDE}}


def _simulate_call(eth: Any, tx: dict[str, Any]) -> dict[str, Any]:
    """Check execution, then collect an advisory gas estimate without changing state."""
    from web3.exceptions import ContractLogicError

    overrides = _gas_balance_override(tx)
    call_args: tuple[Any, ...] = (tx,) if overrides is None else (tx, "latest", overrides)
    try:
        eth.call(*call_args)
    except ContractLogicError as exc:
        return {"success": False, "revert_reason": _revert_reason(exc)}
    except Exception as exc:
        return {"success": False, "error": f"eth_call failed: {redact_error_text(str(exc))}"}
    try:
        if overrides is None:
            return {"gas": int(eth.estimate_gas(tx))}
        return {"gas": int(eth.estimate_gas(tx, "latest", overrides))}
    except Exception as exc:
        return {"gas_error": f"eth_estimateGas failed: {redact_error_text(str(exc))}"}


# Common Solidity/ERC error selectors → readable names (best-effort; extend as needed).
_KNOWN_ERRORS = {
    "0x08c379a0": "Error(string)",  # require/revert("...")
    "0x4e487b71": "Panic(uint256)",  # assert / overflow / div-by-zero
    "0xe450d38c": "ERC20InsufficientBalance",
    "0xfb8f41b2": "ERC20InsufficientAllowance",
}


def _revert_reason(exc: Exception) -> str:
    """Turn a web3 call exception into a concise, readable revert reason.

    Decodes a plain ``Error(string)`` revert to its message, names known custom-error
    selectors, and otherwise reports the 4-byte selector — instead of dumping raw calldata.
    """
    import re

    msg = str(getattr(exc, "message", None) or exc)
    data = getattr(exc, "data", None)
    hexes = re.findall(r"0x[0-9a-fA-F]{8,}", data if isinstance(data, str) else msg)
    if not hexes:
        return redact_error_text(msg)[:160]
    data = hexes[0]
    selector = data[:10]
    if selector == "0x08c379a0":  # Error(string) — try to decode the message
        try:
            from eth_abi import decode

            text = decode(["string"], bytes.fromhex(data[10:]))[0]
            return f'"{redact_error_text(text)}"'
        except Exception:
            pass
    return _KNOWN_ERRORS.get(selector, f"custom error {selector}")


def simulate(
    fn: Any,
    ctx: Any,
    safe: Any,
    *,
    network: str,
    safe_shortname: str,
    execute: bool = True,
    nonce: int | None = None,
) -> SimulationResult:
    """Build and simulate the tx, returning a :class:`SimulationResult`.

    Always computes the SafeTx hash, nonce, and decoded calls. When ``execute`` is true,
    it also builds a **per-call simulation trace** (see :func:`simulate_trace`):
    ``eth_call`` + ``estimate_gas`` each inner call from the Safe, capturing
    ``Contract.method(args) → ok/revert, gas≈N`` — no signatures, no impersonated
    ``execTransaction``, and no Tx Service call. ``success``/``traces`` are derived
    from the trace.
    """
    batch = build(fn, ctx, safe)
    safe_tx, safe_tx_hash, nonce = build_safe_tx(batch, safe, nonce=nonce)

    success = True
    traces: tuple[str, ...] = ()
    call_sims: tuple[CallSim, ...] = ()
    if execute:
        call_sims = simulate_trace(batch, safe, require_ordered=True)
        success = all(c.success for c in call_sims)
        traces = tuple(
            f"call failed: {c.target}: {c.error or c.revert_reason}"
            for c in call_sims
            if not c.success
        )

    return SimulationResult(
        fn_name=getattr(fn, "__name__", str(fn)),
        network=network,
        chain_id=ctx.chain_id,
        safe_address=ctx.safe_address,
        safe_shortname=safe_shortname,
        nonce=nonce,
        safe_tx_hash=safe_tx_hash,
        decoded_calls=decode_calls(batch),
        call_sims=call_sims,
        tx_fields=safe_tx_fields(safe_tx),
        traces=traces,
        success=success,
    )
