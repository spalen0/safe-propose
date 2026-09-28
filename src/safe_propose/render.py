"""Human-readable rendering of simulation results and PR-comment bodies.

The output keeps ``safe_tx_hash`` stable and greppable. Dry runs omit the proposal
nonce/queue footer. PR comments use the same renderer without the terminal's code diff.

Unlike the roboanimals bot, the block includes the **full calldata** a signer is signing
— the EIP-712 SafeTx (``to``/``value``/``operation``/``data``) plus each inner call's
calldata — so signers can verify byte-for-byte before approving.
"""

from __future__ import annotations

import json

from safe_propose.config import redact_error_text
from safe_propose.engine import CallSim, SimulationResult

# Stable line prefixes — keep these exact; they are part of the output contract.
HASH_PREFIX = "safe_tx_hash:"

_OPERATION = {0: "CALL", 1: "DELEGATECALL"}


def render_calls(result: SimulationResult) -> str:
    """Render full decoded arguments and copyable calldata for each numbered call."""
    if not result.decoded_calls:
        return "  (no calls)"
    lines = []
    sims = {c.index: c for c in result.call_sims}
    for i, c in enumerate(result.decoded_calls, start=1):
        sim = sims.get(i)
        fn = sim.label if sim else c.function or "<unknown>"
        args = sim.args if sim else c.args
        decoded = {"to": c.target, "value": c.value, "method": fn, "arguments": args}
        lines += [
            f"#### [{i}] {fn}",
            "",
            "```json",
            json.dumps(decoded, indent=2, default=_json_default),
            "```",
            "",
        ]
        if c.data:
            lines += [_calldata_details("Call calldata", c.data), ""]
    return "\n".join(lines)


def _json_default(value: object) -> str:
    if isinstance(value, bytes | bytearray):
        return "0x" + bytes(value).hex()
    raise TypeError(f"Cannot render transaction argument of type {type(value).__name__}")


def _calldata_details(label: str, data: str) -> str:
    size = (len(data.removeprefix("0x"))) // 2
    return (
        f"<details>\n<summary>{label} ({size:,} bytes)</summary>\n\n"
        f"```text\n{data}\n```\n\n</details>"
    )


def _fmt_arg(value: object) -> str:
    """Compactly stringify a decoded argument; long hex/strings get an ellipsis.

    Bytes-like values (Ape decodes ``bytes``/``bytes32`` inputs as ``HexBytes``) are
    rendered as ``0x…`` hex, not Python ``b'\\xee…'`` text, so a reviewer can match the
    trace against on-chain values (e.g. a Morpho market id).
    """
    if isinstance(value, bytes | bytearray):
        s = "0x" + bytes(value).hex()
    else:
        s = str(value)
    if s.startswith("0x") and len(s) > 12:
        return f"{s[:6]}…{s[-4:]}"
    if len(s) > 32:
        return f"{s[:29]}…"
    return s


def render_call_sim(c: CallSim) -> str:
    """One brownie-style trace line for a call: ``[i] Contract.method(args) ok gas≈N``.

    Shared by the dry-run trace section and ``send``'s pre-flight failure message, so a
    reverting call reads the same in both places.
    """
    args = ", ".join(_fmt_arg(a) for a in c.args)
    val = f"  value={c.value}" if c.value else ""
    if c.success:
        gas = f"gas≈{c.gas:,}" if c.gas is not None else "gas≈?"
        status = f"ok   {gas}"
        if c.gas_error:
            status += f"   {redact_error_text(c.gas_error)}"
    elif c.error:
        status = f"ERROR: {redact_error_text(c.error)}"
    else:
        status = f"REVERTED: {redact_error_text(c.revert_reason)}"
    return f"[{c.index}] {c.label}({args}){val}   {status}"


def render_trace(result: SimulationResult) -> str:
    """Render the brownie-style per-call simulation trace, one line per inner call.

    Example: ``[1] MetaMorphoV1_1.submitCap(0xee7d…1234, 6000000)   ok   gas≈62,870``.
    Returns ``""`` when no trace was captured (e.g. ``--no-execute``).
    """
    if not result.call_sims:
        return ""
    lines = ["### Simulation (per-call, from the Safe)", "", "```text"]
    lines += [f"  {render_call_sim(c)}" for c in result.call_sims]
    lines.append("```")
    return "\n".join(lines)


def render_signable(
    *,
    safe_address: str,
    chain_id: int,
    tx_fields: dict,
    safe_tx_hash: str,
) -> str:
    """Render the EIP-712 SafeTx message and its full payload for wallet verification.

    Shared by ``dry-run`` (via the rendered block) and ``send`` (printed before proposing).
    """
    f = tx_fields
    op = _OPERATION.get(f.get("operation"), str(f.get("operation")))
    lines = [
        "### Transaction to sign (verify in your wallet)",
        "",
        "```text",
        f"Safe (verifyingContract): {safe_address}",
        f"chainId: {chain_id}",
        "--- EIP-712 SafeTx (what you sign) ---",
        f"to:             {f.get('to')}",
        f"value:          {f.get('value')}",
        f"operation:      {f.get('operation')} ({op})",
        f"safeTxGas:      {f.get('safeTxGas')}",
        f"baseGas:        {f.get('baseGas')}",
        f"gasPrice:       {f.get('gasPrice')}",
        f"gasToken:       {f.get('gasToken')}",
        f"refundReceiver: {f.get('refundReceiver')}",
        f"nonce:          {f.get('nonce')}",
        f"{HASH_PREFIX} {safe_tx_hash}",
        "```",
        "",
        _calldata_details("SafeTx data (signed payload)", f.get("data", "0x")),
    ]
    return "\n".join(lines)


def render_tx_to_sign(result: SimulationResult) -> str:
    """The signable-tx block for a :class:`SimulationResult` (used by ``render_block``)."""
    return render_signable(
        safe_address=result.safe_address,
        chain_id=result.chain_id,
        tx_fields=result.tx_fields,
        safe_tx_hash=result.safe_tx_hash,
    )


def render_block(result: SimulationResult, *, diff: str | None = None) -> str:
    """Render the dry-run block: optional code diff, calls, typed-data preview, and hash.

    No proposal footer is shown because nothing is queued. Failed reports omit the
    typed-data preview.
    """
    lines: list[str] = [
        f"## safe-propose: {result.fn_name} on {result.network} (chain {result.chain_id})",
        "",
        f"pre-flight (per-call): {'ok ✅' if result.success else 'FAILED ❌'}",
        "",
    ]

    if diff is not None:
        body = diff.rstrip() or "(no diff vs base)"
        lines += ["### Code diff", "```diff", body, "```", ""]

    lines += ["### Simulated batch", "", render_calls(result), ""]

    # Brownie-style per-call trace (Contract.method(args) → ok/revert, gas≈N), when captured.
    trace_block = render_trace(result)
    if trace_block:
        lines += [trace_block, ""]

    # Per-call pre-flight from the Safe in batch order on a fork (see engine.simulate_trace).
    # "ok" means no call reverts given the calls before it.
    if not result.call_sims and result.traces:
        lines += ["```text", *(redact_error_text(t) for t in result.traces), "```"]
    lines.append("")

    if result.success:
        lines.append(render_tx_to_sign(result))
    else:
        lines.append(f"{HASH_PREFIX} {result.safe_tx_hash}")
    return "\n".join(lines)
