"""Unit tests for render.py + the SimulationResult shape (TEST_PLAN Layer 1)."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from safe_propose.config import DEFAULT_SAFE_QUEUE_URL, format_queue_url
from safe_propose.engine import CallSim, DecodedCall, SimulationResult
from safe_propose.render import render_block, render_trace


def _result() -> SimulationResult:
    return SimulationResult(
        fn_name="katana_caps",
        network="katana",
        chain_id=747474,
        safe_address="0x90D0f26025571295D18a6c041E47450B81886B51",
        safe_shortname="katana",
        nonce=20,
        safe_tx_hash="0xabc123",
        decoded_calls=(
            DecodedCall(
                target="0xVault",
                function="submitCap",
                args=("market", 6_000_000),
                data="0x095ea7b300000000",
            ),
        ),
        tx_fields={
            "to": "0x9641d764fc13c8B624c04430C7356C1C7C8102e2",
            "value": 0,
            "data": "0x8d80ff0adeadbeef",
            "operation": 1,
            "safeTxGas": 11,
            "baseGas": 22,
            "gasPrice": 33,
            "gasToken": "0x000000000000000000000000000000000000aaaa",
            "refundReceiver": "0x000000000000000000000000000000000000bbbb",
            "nonce": 20,
        },
        call_sims=(
            CallSim(
                index=1,
                target="0xVault",
                contract_name="MetaMorphoV1_1",
                method="submitCap",
                args=("0xee7d000000000000000000000000000000001234", 6_000_000),
                gas=62_870,
            ),
        ),
    )


def test_queue_url_format():
    assert format_queue_url(
        DEFAULT_SAFE_QUEUE_URL, "katana", "0x90D0f26025571295D18a6c041E47450B81886B51"
    ) == (
        "https://app.safe.global/transactions/queue"
        "?safe=katana:0x90D0f26025571295D18a6c041E47450B81886B51"
    )


def test_custom_queue_url_format():
    assert format_queue_url(
        "https://multisig.risechain.com/home",
        "rise",
        "0x60C6E21be8B2f7118823FbEB15B1be22EAe1de11",
    ) == (
        "https://multisig.risechain.com/home?safe=rise:0x60C6E21be8B2f7118823FbEB15B1be22EAe1de11"
    )


def test_render_block_is_greppable():
    block = render_block(_result(), diff="--- a\n+++ b\n+changed")
    assert "pre-flight (per-call): ok ✅" in block
    assert "safe_tx_hash: 0xabc123" in block
    assert "nonce: 20" not in block.splitlines()
    assert "queue:" not in block
    # diff is included when provided.
    assert "+changed" in block
    assert "submitCap" in block


def test_render_block_includes_full_calldata():
    block = render_block(_result())
    assert "Transaction to sign" in block
    # Verifying context needed to reconstruct/audit the EIP-712 typed data:
    assert "verifyingContract): 0x90D0f26025571295D18a6c041E47450B81886B51" in block
    assert "chainId: 747474" in block
    # ALL ten signed SafeTx fields must be present (a signer must verify each one) —
    # guards the PR #3 review finding that gas/token/refund fields were omitted.
    assert "to:             0x9641d764fc13c8B624c04430C7356C1C7C8102e2" in block
    assert "value:          0" in block
    assert "operation:      1 (DELEGATECALL)" in block
    assert "```text\n0x8d80ff0adeadbeef\n```" in block
    assert "safeTxGas:      11" in block
    assert "baseGas:        22" in block
    assert "gasPrice:       33" in block
    assert "gasToken:       0x000000000000000000000000000000000000aaaa" in block
    assert "refundReceiver: 0x000000000000000000000000000000000000bbbb" in block
    assert "nonce:          20" in block
    assert "safe_tx_hash: 0xabc123" in block
    assert "execTransaction" not in block
    assert "0x6a761202cafe" not in block
    # each inner call's calldata is shown too:
    assert "```text\n0x095ea7b300000000\n```" in block


def test_render_trace_brownie_style():
    block = render_trace(_result())
    # one line per call: Contract.method(args) with truncated hex + grouped gas.
    assert "[1] MetaMorphoV1_1.submitCap(" in block
    assert "0xee7d…1234" in block  # long hex arg is truncated
    assert "6000000" in block
    assert "ok" in block
    assert "gas≈62,870" in block  # gas grouped with thousands separators


def test_render_trace_renders_bytes_args_as_hex():
    # Ape decodes a bytes32 input (e.g. a Morpho market id) as HexBytes; the trace must show
    # 0x… hex a reviewer can match on-chain, not Python b'\xee…' bytes text.
    from hexbytes import HexBytes

    r = _result()
    market_id = HexBytes(b"\xee" * 32)
    call = CallSim(
        index=1,
        target="0xVault",
        contract_name="MetaMorphoV1_1",
        method="submitCap",
        args=(market_id, 6_000_000),
        gas=62_870,
    )
    object.__setattr__(r, "call_sims", (call,))
    block = render_trace(r)
    assert "0xeeee…eeee" in block  # truncated hex, not bytes text
    assert "b'\\x" not in block


def test_render_trace_marks_reverts():
    r = _result()
    failed = CallSim(
        index=2,
        target="0xBad",
        contract_name="Vault",
        method="withdraw",
        args=(),
        success=False,
        revert_reason='"insufficient balance"',
    )
    object.__setattr__(r, "call_sims", (*r.call_sims, failed))
    block = render_trace(r)
    assert "[2] Vault.withdraw()" in block
    assert 'REVERTED: "insufficient balance"' in block


def test_render_trace_empty_when_no_sims():
    r = _result()
    object.__setattr__(r, "call_sims", ())
    assert render_trace(r) == ""
    # render_block must not include the Simulation section either.
    assert "Simulation (per-call" not in render_block(r)


def test_render_block_includes_trace():
    block = render_block(_result())
    assert "Simulation (per-call" in block
    assert "MetaMorphoV1_1.submitCap(" in block


def test_decoded_arguments_are_complete_json_including_nested_bytes():
    r = _result()
    address = "0x" + "ab" * 20
    market = b"\xee" * 32
    call = replace(r.call_sims[0], args=((address, market, 10**30), 0))
    block = render_block(replace(r, call_sims=(call,)))
    decoded = json.loads(re.search(r"```json\n(.*?)\n```", block, re.S).group(1))
    assert decoded["arguments"] == [[address, "0x" + market.hex(), 10**30], 0]
    assert decoded["to"] == r.decoded_calls[0].target
    assert decoded["method"] == call.label
    assert "#### [1]" in block
    assert "<summary>Call calldata (8 bytes)</summary>" in block


def test_rpc_errors_are_not_rendered_as_contract_reverts():
    r = _result()
    call = replace(r.call_sims[0], success=False, error="eth_call failed: RPC unavailable")
    block = render_block(replace(r, success=False, call_sims=(call,)))
    assert "ERROR: eth_call failed: RPC unavailable" in block
    assert "REVERTED" not in block
    assert "pre-flight (per-call): FAILED ❌" in block


def test_render_redacts_rpc_urls_in_error_and_trace_fallback():
    secret = "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey"
    r = _result()
    call = replace(r.call_sims[0], success=False, error=f"eth_call failed: {secret}")
    block = render_block(replace(r, success=False, call_sims=(call,)))
    assert secret not in block
    assert "supersecretkey" not in block
    assert "rpchostkey" not in block
    assert "***url***" in block
    traces = (f"call failed: 0xVault: eth_call failed: {secret}",)
    fallback = render_block(replace(r, success=False, call_sims=(), traces=traces))
    assert secret not in fallback
    assert "***url***" in fallback


def test_failed_report_omits_signing_section_nonce_and_queue():
    r = _result()
    failed = replace(r.call_sims[0], success=False, revert_reason="not curator")
    block = render_block(replace(r, success=False, call_sims=(failed,)))
    assert "pre-flight (per-call): FAILED ❌" in block
    assert "REVERTED: not curator" in block
    secret = "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey"
    leaked = replace(r.call_sims[0], success=False, revert_reason=secret)
    redacted = render_block(replace(r, success=False, call_sims=(leaked,)))
    assert secret not in redacted
    assert "supersecretkey" not in redacted
    assert "```text\n0x095ea7b300000000\n```" in block
    assert "safe_tx_hash: 0xabc123" in block
    assert "nonce:" not in block
    assert "queue:" not in block
    assert "Transaction to sign" not in block
    assert "execTransaction calldata to the Safe" not in block


def test_gas_estimation_diagnostic_is_visible():
    r = _result()
    call = replace(r.call_sims[0], gas=None, gas_error="eth_estimateGas failed: timeout")
    assert "ok   gas≈?   eth_estimateGas failed: timeout" in render_trace(
        replace(r, call_sims=(call,))
    )
