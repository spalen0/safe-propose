"""CLI unit tests with the network layer mocked (Tasks 07/08/09)."""

from __future__ import annotations

import contextlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from safe_propose.cli import main
from safe_propose.engine import CallSim, DecodedCall, SimulationResult

SAFE = "0x90D0f26025571295D18a6c041E47450B81886B51"


def _sim_result(fn="alpha"):
    return SimulationResult(
        fn_name=fn,
        network="katana",
        chain_id=747474,
        safe_address=SAFE,
        safe_shortname="katana",
        nonce=7,
        safe_tx_hash="0xabc123",
        decoded_calls=(DecodedCall(target="0xVault", function="0x095ea7b3", args=(), value=0),),
    )


def _mock_connect(monkeypatch):
    @contextlib.contextmanager
    def fake_connect(config, *, fork, net_name="mainnet"):
        yield object()

    monkeypatch.setattr("safe_propose.runtime.connect", fake_connect)
    monkeypatch.setattr("safe_propose.runtime.make_ctx", lambda config, const=None: object())
    monkeypatch.setattr("safe_propose.runtime.safe_onchain_nonce", lambda safe: 7)


def test_help_runs():
    res = CliRunner().invoke(main, ["--help"])
    assert res.exit_code == 0
    assert "dry-run" in res.output
    assert "send" in res.output


def test_dry_run_help_shows_default_txs_file():
    res = CliRunner().invoke(main, ["dry-run", "--help"])
    assert res.exit_code == 0
    assert "--txs-file" in res.output
    assert "scripts/safe_txs.py" in res.output


def test_dry_run_renders_block(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "https://rpc.example")
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "+changed line")
    monkeypatch.setattr("safe_propose.engine.simulate", lambda *a, **k: _sim_result())

    res = CliRunner().invoke(
        main,
        [
            "dry-run",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
            "--constants-file",
            str(fixtures_dir / "sample_constants.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "safe_tx_hash: 0xabc123" in res.output
    assert "nonce: 7" not in res.output.splitlines()
    assert "queue:" not in res.output
    assert "+changed line" in res.output


@pytest.mark.parametrize("per_chain", [True, False])
def test_dry_run_warns_on_eth_safe_address_fallback(monkeypatch, fixtures_dir, per_chain):
    monkeypatch.setenv("ETH_SAFE_ADDRESS", SAFE)
    if per_chain:
        monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    else:
        monkeypatch.delenv("KATANA_SAFE_ADDRESS", raising=False)
    monkeypatch.setenv("KATANA_RPC", "https://rpc.example")
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "")
    monkeypatch.setattr("safe_propose.engine.simulate", lambda *a, **k: _sim_result())

    res = CliRunner(mix_stderr=False).invoke(
        main,
        [
            "dry-run",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
            "--constants-file",
            str(fixtures_dir / "sample_constants.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    warned = "warning: KATANA_SAFE_ADDRESS is unset; using ETH_SAFE_ADDRESS" in res.stderr
    assert warned is not per_chain


def test_dry_run_post_comment(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "+private diff text")
    monkeypatch.setattr("safe_propose.engine.simulate", lambda *a, **k: _sim_result())
    calls = {}
    monkeypatch.setattr(
        "safe_propose.gitutil.post_comment",
        lambda body, pr=None: calls.update(body=body) or (True, "posted comment to PR #5"),
    )

    res = CliRunner().invoke(
        main,
        [
            "dry-run",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--post-comment",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "posted comment to PR #5" in res.output
    assert "safe_tx_hash: 0xabc123" in calls["body"]
    assert "nonce: 7" not in calls["body"].splitlines()
    assert "queue:" not in calls["body"]
    assert "execTransaction" not in calls["body"]
    assert "Code diff" not in calls["body"]
    assert "+private diff text" not in calls["body"]


@pytest.mark.parametrize("post_comment", [False, True])
def test_dry_run_exits_nonzero_after_rendering_failure(monkeypatch, fixtures_dir, post_comment):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "")
    failed = replace(_sim_result(), success=False, traces=("eth_call failed: RPC unavailable",))
    monkeypatch.setattr("safe_propose.engine.simulate", lambda *a, **k: failed)
    posted = []
    monkeypatch.setattr(
        "safe_propose.gitutil.post_comment", lambda body: (posted.append(body) or True, "posted")
    )
    args = [
        "dry-run",
        "--fn",
        "alpha",
        "--network",
        "katana",
        "--txs-file",
        str(fixtures_dir / "sample_txs.py"),
    ]
    if post_comment:
        args.append("--post-comment")
    res = CliRunner().invoke(main, args)
    assert res.exit_code == 1
    assert "pre-flight (per-call): FAILED" in res.output
    assert "safe_tx_hash: 0xabc123" in res.output
    assert "RPC unavailable" in res.output
    assert "pre-flight (per-call): FAILED ❌" in res.output
    assert "nonce:" not in res.output
    assert "queue:" not in res.output
    assert len(posted) == int(post_comment)
    if post_comment:
        assert "pre-flight (per-call): FAILED" in posted[0]
        assert "nonce:" not in posted[0]
        assert "queue:" not in posted[0]


SECRET_RPC = "https://user:pass@rpchostkey.rpc.example/v2/supersecretkey"


@pytest.mark.parametrize("post_comment", [False, True])
def test_dry_run_redacts_rpc_url_in_failed_report(monkeypatch, fixtures_dir, post_comment):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", SECRET_RPC)
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "")
    failed = replace(
        _sim_result(),
        success=False,
        call_sims=(
            CallSim(
                index=1,
                target="0xVault",
                contract_name="Vault",
                method="submitCap",
                args=(),
                success=False,
                error=f"eth_call failed: 401 Client Error for url: {SECRET_RPC}",
            ),
        ),
        traces=(f"call failed: 0xVault: eth_call failed: 401 for url: {SECRET_RPC}",),
    )
    monkeypatch.setattr("safe_propose.engine.simulate", lambda *a, **k: failed)
    posted = []
    monkeypatch.setattr(
        "safe_propose.gitutil.post_comment", lambda body: (posted.append(body) or True, "posted")
    )
    args = [
        "dry-run",
        "--fn",
        "alpha",
        "--network",
        "katana",
        "--txs-file",
        str(fixtures_dir / "sample_txs.py"),
    ]
    if post_comment:
        args.append("--post-comment")
    res = CliRunner().invoke(main, args)
    assert res.exit_code == 1
    for blob in (res.output, *posted):
        assert SECRET_RPC not in blob
        assert "supersecretkey" not in blob
        assert "rpchostkey" not in blob
        assert "***" in blob
    if post_comment:
        assert "ERROR:" in posted[0]


def test_dry_run_redacts_rpc_url_in_cli_exception(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", SECRET_RPC)

    @contextlib.contextmanager
    def fake_connect(config, *, fork):
        raise RuntimeError(f"401 Client Error for url: {SECRET_RPC}")
        yield object()  # pragma: no cover

    monkeypatch.setattr("safe_propose.runtime.connect", fake_connect)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "")
    res = CliRunner().invoke(
        main,
        [
            "dry-run",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 1
    assert "dry-run failed" in res.output
    assert SECRET_RPC not in res.output
    assert "supersecretkey" not in res.output
    assert "rpchostkey" not in res.output
    assert "***" in res.output


def test_dry_run_unknown_fn_fails_clearly(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    res = CliRunner().invoke(
        main,
        [
            "dry-run",
            "--fn",
            "does_not_exist",
            "--network",
            "katana",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code != 0
    assert "alpha" in res.output  # lists available names


@pytest.mark.parametrize("pr_flag", [None, "--label-pr", "--close-pr"])
@pytest.mark.parametrize("outcome", ["success", "proposal_failure", "cancel", "github_failure"])
def test_send_proposes_once(monkeypatch, fixtures_dir, pr_flag, outcome):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)  # → keyless Katana override
    monkeypatch.delenv("KATANA_TX_SERVICE_URL", raising=False)
    secret_url = None
    if pr_flag is None and outcome == "success":
        secret_url = "https://hostkey.svc.example/api?key=querysecret"
        monkeypatch.setenv("KATANA_TX_SERVICE_URL", secret_url)
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.runtime.proposal_nonce", lambda safe, endpoint: 20)
    monkeypatch.setattr("safe_propose.engine.build", lambda fn, ctx, safe: object())
    monkeypatch.setattr("safe_propose.engine.simulate_trace", lambda batch, safe, **k: ())
    monkeypatch.setattr(
        "safe_propose.engine.build_safe_tx",
        lambda batch, safe, nonce=None: (object(), "0xdeadbeef", 7),
    )
    monkeypatch.setattr(
        "safe_propose.engine.safe_tx_fields",
        lambda safe_tx: {
            "to": "0x9641",
            "value": 0,
            "data": "0x8d80ff0a",
            "operation": 1,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x" + "0" * 40,
            "refundReceiver": "0x" + "0" * 40,
            "nonce": 20,
        },
    )
    monkeypatch.setattr("safe_propose.runtime.load_proposer", lambda config: object())
    proposed = {}

    def propose(safe, safe_tx, endpoint, submitter):
        if outcome == "proposal_failure":
            raise RuntimeError("service unavailable")
        proposed.update(url=endpoint.base_url, n=proposed.get("n", 0) + 1)

    monkeypatch.setattr("safe_propose.runtime.propose", propose)
    updates = []

    def update_pr(network, nonce, *, close):
        assert proposed["n"] == 1
        updates.append((network, nonce, close))
        return (
            outcome != "github_failure",
            "permission denied" if outcome == "github_failure" else "ok",
        )

    monkeypatch.setattr("safe_propose.notify.label_pr", update_pr)
    notifications = []

    def notification(*args, **kwargs):
        assert proposed["n"] == 1
        if pr_flag == "--close-pr":
            assert updates == [("katana", 7, True)]
        notifications.append(args)
        return True, "sent"

    monkeypatch.setattr("safe_propose.notify.proposal_notification", notification)
    deletions = []

    def delete_branch():
        assert updates == [("katana", 7, True)]
        assert len(notifications) == 1
        deletions.append(True)
        return True, "deleted"

    monkeypatch.setattr("safe_propose.notify.delete_pr_branch", delete_branch)

    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            *([] if outcome == "cancel" else ["--yes"]),
            *([pr_flag] if pr_flag else []),
            "--notify",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
        input="n\n",
    )
    if outcome in {"proposal_failure", "cancel"}:
        assert res.exit_code != 0
        assert updates == []
        assert proposed == {}
        assert notifications == []
        assert deletions == []
        return
    assert res.exit_code == 0, res.output
    assert updates == ([("katana", 7, pr_flag == "--close-pr")] if pr_flag else [])
    if outcome == "github_failure" and pr_flag:
        assert (
            "PR update skipped or failed; transaction already queued; do not resend" in res.output
        )
        assert "fix the PR manually" not in res.output
    assert len(notifications) == int(not (outcome == "github_failure" and pr_flag == "--close-pr"))
    assert len(deletions) == int(pr_flag == "--close-pr" and outcome != "github_failure")
    assert proposed["n"] == 1  # proposed exactly once
    assert proposed["url"] == (secret_url or "https://safe-transaction-katana.safe.global/api")
    assert "tx-service: override" in res.output
    assert "(timeout=10.0s)" in res.output
    if secret_url:
        assert "https://hostkey.svc.example" in res.output
    else:
        assert "https://safe-transaction-katana.safe.global" in res.output
    assert "querysecret" not in res.output
    assert "safe_tx_hash: 0xdeadbeef" in res.output
    assert "```text\n0x8d80ff0a\n```" in res.output  # full EIP-712 SafeTx data shown
    assert "execTransaction" not in res.output
    assert "nonce: 7" in res.output.splitlines()
    assert "queue: https://app.safe.global" in res.output


@pytest.mark.parametrize("rpc_error", [False, True])
def test_send_aborts_when_simulation_fails(monkeypatch, fixtures_dir, rpc_error):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.engine.build", lambda fn, ctx, safe: object())
    monkeypatch.setattr(
        "safe_propose.engine.simulate_trace",
        lambda batch, safe, **k: (
            CallSim(
                index=1,
                target="0xVault",
                contract_name="Vault",
                method="submitCap",
                args=(),
                success=False,
                revert_reason="" if rpc_error else '"not curator"',
                error="eth_call failed: RPC unavailable" if rpc_error else "",
            ),
        ),
    )
    proposed = {"n": 0}
    updates = []
    monkeypatch.setattr(
        "safe_propose.notify.label_pr", lambda *a, **k: updates.append(a) or (True, "ok")
    )
    monkeypatch.setattr(
        "safe_propose.runtime.propose",
        lambda *a, **k: proposed.update(n=proposed["n"] + 1) or "0x",
    )

    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--close-pr",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code != 0
    assert "pre-flight failed" in res.output
    # the failing call is shown with the same friendly trace line as the dry-run.
    if rpc_error:
        assert "ERROR: eth_call failed: RPC unavailable" in res.output
        assert "REVERTED" not in res.output
    else:
        assert 'Vault.submitCap()   REVERTED: "not curator"' in res.output
    assert proposed["n"] == 0  # never proposed a reverting tx
    assert updates == []


def test_send_redacts_rpc_url_in_failed_preflight(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", SECRET_RPC)
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.engine.build", lambda fn, ctx, safe: object())
    monkeypatch.setattr(
        "safe_propose.engine.simulate_trace",
        lambda batch, safe, **k: (
            CallSim(
                index=1,
                target="0xVault",
                contract_name="Vault",
                method="submitCap",
                args=(),
                success=False,
                error=f"eth_call failed: 401 Client Error for url: {SECRET_RPC}",
            ),
        ),
    )
    proposed = {"n": 0}
    monkeypatch.setattr(
        "safe_propose.runtime.propose",
        lambda *a, **k: proposed.update(n=proposed["n"] + 1) or "0x",
    )
    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 1
    assert "pre-flight failed" in res.output
    assert SECRET_RPC not in res.output
    assert "supersecretkey" not in res.output
    assert "rpchostkey" not in res.output
    assert "***" in res.output
    assert proposed["n"] == 0


def test_send_redacts_rpc_url_in_cli_exception(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", SECRET_RPC)
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)

    @contextlib.contextmanager
    def fake_connect(config, *, fork):
        raise RuntimeError(f"401 Client Error for url: {SECRET_RPC}")
        yield object()  # pragma: no cover

    monkeypatch.setattr("safe_propose.runtime.connect", fake_connect)
    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 1
    assert "send failed" in res.output
    assert SECRET_RPC not in res.output
    assert "supersecretkey" not in res.output
    assert "rpchostkey" not in res.output
    assert "***" in res.output


def test_send_preflights_on_fork_and_proposes_on_live(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)
    events = []

    @contextlib.contextmanager
    def fake_connect(config, *, fork, net_name="mainnet"):
        events.append(("connect", fork))
        yield "fork-safe" if fork else "live-safe"
        events.append(("disconnect", fork))

    monkeypatch.setattr("safe_propose.runtime.connect", fake_connect)
    monkeypatch.setattr("safe_propose.runtime.make_ctx", lambda config, const=None: object())
    monkeypatch.setattr("safe_propose.engine.build", lambda fn, ctx, safe: f"batch@{safe}")
    monkeypatch.setattr(
        "safe_propose.engine.simulate_trace",
        lambda batch, safe, **k: events.append(("simulate", batch, safe, k)) or (),
    )
    monkeypatch.setattr("safe_propose.runtime.proposal_nonce", lambda safe, endpoint: 20)
    monkeypatch.setattr(
        "safe_propose.engine.build_safe_tx",
        lambda batch, safe, nonce=None: (
            events.append(("build_safe_tx", batch, safe)) or (object(), "0xhash", nonce)
        ),
    )
    monkeypatch.setattr(
        "safe_propose.engine.safe_tx_fields",
        lambda safe_tx: {
            "to": "0x96",
            "value": 0,
            "data": "0x",
            "operation": 1,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0",
            "refundReceiver": "0x0",
            "nonce": 20,
        },
    )
    monkeypatch.setattr("safe_propose.runtime.load_proposer", lambda config: object())
    monkeypatch.setattr(
        "safe_propose.runtime.propose",
        lambda safe, safe_tx, endpoint, submitter: events.append(("propose", safe)),
    )

    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert events == [
        ("connect", True),
        ("simulate", "batch@fork-safe", "fork-safe", {"require_ordered": True}),
        ("disconnect", True),
        ("connect", False),
        ("build_safe_tx", "batch@fork-safe", "live-safe"),
        ("propose", "live-safe"),
        ("disconnect", False),
    ]


def test_send_queues_the_preflighted_batch(monkeypatch, fixtures_dir):
    """A moving chain read is taken from the fork build, which is the simulated batch."""
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)

    @contextlib.contextmanager
    def fake_connect(config, *, fork, net_name="mainnet"):
        yield "fork-safe" if fork else "live-safe"

    built = []

    def build(fn, ctx, safe):
        built.append(safe)
        amount = b"\x01" if safe == "fork-safe" else b"\x02"
        return SimpleNamespace(calls=[{"target": "0xToken", "value": 0, "callData": amount}])

    monkeypatch.setattr("safe_propose.runtime.connect", fake_connect)
    monkeypatch.setattr("safe_propose.runtime.make_ctx", lambda config, const=None: object())
    monkeypatch.setattr("safe_propose.engine.build", build)
    monkeypatch.setattr("safe_propose.engine.simulate_trace", lambda batch, safe, **k: ())
    seen = {}

    def build_safe_tx(batch, safe, nonce=None):
        seen.update(batch=batch, safe=safe)
        return object(), "0xhash", nonce

    monkeypatch.setattr("safe_propose.runtime.proposal_nonce", lambda safe, endpoint: 7)
    monkeypatch.setattr("safe_propose.engine.build_safe_tx", build_safe_tx)
    monkeypatch.setattr(
        "safe_propose.engine.safe_tx_fields",
        lambda safe_tx: {
            "to": "0x96",
            "value": 0,
            "data": "0x",
            "operation": 1,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0",
            "refundReceiver": "0x0",
            "nonce": 7,
        },
    )
    proposed = []
    monkeypatch.setattr("safe_propose.runtime.load_proposer", lambda config: object())
    monkeypatch.setattr(
        "safe_propose.runtime.propose",
        lambda *a, **k: proposed.append("proposed"),
    )

    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert built == ["fork-safe"]
    assert seen["safe"] == "live-safe"
    assert seen["batch"].calls[0]["callData"] == b"\x01"
    assert proposed == ["proposed"]


def test_dry_run_nonce_override(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.gitutil.code_diff", lambda base: "")
    seen = {}
    monkeypatch.setattr(
        "safe_propose.engine.simulate",
        lambda *a, **k: seen.update(nonce=k.get("nonce")) or _sim_result(),
    )
    res = CliRunner().invoke(
        main,
        [
            "dry-run",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--nonce",
            "12",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert seen["nonce"] == 12  # --nonce passed straight through to simulate


def test_send_nonce_override_replaces(monkeypatch, fixtures_dir):
    monkeypatch.setenv("KATANA_SAFE_ADDRESS", SAFE)
    monkeypatch.setenv("KATANA_RPC", "x")
    monkeypatch.delenv("APE_SAFE_GATEWAY_API_KEY", raising=False)
    _mock_connect(monkeypatch)
    monkeypatch.setattr("safe_propose.engine.build", lambda fn, ctx, safe: object())
    monkeypatch.setattr("safe_propose.engine.simulate_trace", lambda batch, safe, **k: ())
    seen = {}
    monkeypatch.setattr(
        "safe_propose.engine.build_safe_tx",
        lambda batch, safe, nonce=None: seen.update(nonce=nonce) or (object(), "0xhash", nonce),
    )
    monkeypatch.setattr(
        "safe_propose.engine.safe_tx_fields",
        lambda safe_tx: {
            "to": "0x96",
            "value": 0,
            "data": "0x",
            "operation": 1,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0",
            "refundReceiver": "0x0",
            "nonce": 12,
        },
    )
    monkeypatch.setattr("safe_propose.runtime.load_proposer", lambda config: object())
    # If --nonce is honored, proposal_nonce must NOT be consulted.
    monkeypatch.setattr(
        "safe_propose.runtime.proposal_nonce",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("proposal_nonce should be skipped")),
    )
    monkeypatch.setattr("safe_propose.runtime.propose", lambda *a, **k: "0xhash")

    res = CliRunner().invoke(
        main,
        [
            "send",
            "--fn",
            "alpha",
            "--network",
            "katana",
            "--yes",
            "--nonce",
            "12",
            "--txs-file",
            str(fixtures_dir / "sample_txs.py"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert seen["nonce"] == 12  # build_safe_tx got the overridden nonce
    assert "overriding nonce to 12" in res.output  # REPLACES note shown
