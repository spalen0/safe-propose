"""Command-line interface: ``safe-propose dry-run`` and ``safe-propose send``.

``dry-run`` (Task 07): resolve config → load fn → connect a fork → build + simulate →
render the code diff + decoded calls + EIP-712 preview + ``safe_tx_hash``, with optional
``--post-comment`` (Task 08). Nothing is queued, so there is no proposal nonce/queue
footer. ``send`` (Task 09): pre-flight on a fork, then propose to the Safe Tx Service
(override URL for chains the default client does not support, e.g. Katana) and print
the queue link + nonce. Network-touching modules are imported lazily so ``--help``
and config errors never require Ape or a connection.
"""

from __future__ import annotations

import sys

import click

from safe_propose import __version__
from safe_propose.config import ConfigError, redact_error_text, resolve_config
from safe_propose.loader import DEFAULT_TXS_FILE, load_constants, load_definitions, resolve
from safe_propose.registry import UnknownDefinitionError


def _fail(message: str, code: int = 1) -> None:
    """Print an error to stderr and exit non-zero (never hang, always actionable)."""
    click.echo(f"error: {redact_error_text(message)}", err=True)
    raise SystemExit(code)


@click.group()
@click.version_option(__version__, prog_name="safe-propose")
def main() -> None:
    """Build, simulate, and propose Gnosis Safe transactions (Ape + ape-safe)."""


_common_options = [
    click.option("--fn", "fn_name", required=True, help="Name of the @txn function to run."),
    click.option("--network", required=True, help="Target network (e.g. katana, ethereum)."),
    click.option(
        "--txs-file",
        default=DEFAULT_TXS_FILE,
        show_default=True,
        help="Path to the tx-definition module. Override if it is not scripts/safe_txs.py.",
    ),
    click.option(
        "--constants-file",
        default="constants.py",
        show_default=True,
        help="Optional module providing ctx.const values.",
    ),
    click.option("--safe-address", default=None, help="Override the resolved Safe address."),
    click.option("--rpc-uri", default=None, help="Override the network RPC URI."),
]


def _add_options(fn):  # noqa: ANN001 - tiny decorator helper
    for opt in reversed(_common_options):
        fn = opt(fn)
    return fn


def _resolve(fn_name, network, txs_file, constants_file, safe_address, rpc_uri):  # noqa: ANN001
    """Shared path: resolve config + load the selected tx fn. Returns (config, fn, const)."""
    try:
        config = resolve_config(
            network,
            cli={"safe_address": safe_address, "rpc_uri": rpc_uri},
        )
    except ConfigError as exc:
        _fail(str(exc))
    if config.safe_address_fallback:
        click.echo(
            f"warning: {config.env_prefix}_SAFE_ADDRESS is unset; using ETH_SAFE_ADDRESS "
            f"({config.safe_address}) on {config.network}. Set {config.env_prefix}_SAFE_ADDRESS "
            "if the Safe lives at a different address on this chain.",
            err=True,
        )

    try:
        load_definitions(txs_file)
        fn = resolve(fn_name)
    except FileNotFoundError as exc:
        _fail(str(exc))
    except UnknownDefinitionError as exc:
        _fail(str(exc))

    const = load_constants(constants_file)
    return config, fn, const


@main.command("dry-run")
@_add_options
@click.option("--base", default=None, help="Git base ref for the diff (default: origin default).")
@click.option("--post-comment", is_flag=True, help="Post the rendered block to the PR via gh.")
@click.option(
    "--execute/--no-execute",
    default=True,
    help="Simulate each inner call via eth_call from the Safe (revert check). On by default.",
)
@click.option(
    "--nonce",
    type=int,
    default=None,
    help="Override the Safe nonce (e.g. to preview replacing an already-queued tx).",
)
def dry_run(
    fn_name,
    network,
    txs_file,
    constants_file,
    safe_address,
    rpc_uri,
    base,
    post_comment,
    execute,
    nonce,
):  # noqa: ANN001
    """Validate + simulate a transaction; print diff, decoded calls, hash, and EIP-712 preview."""
    from safe_propose import engine, gitutil, render, runtime

    config, fn, const = _resolve(fn_name, network, txs_file, constants_file, safe_address, rpc_uri)
    diff = gitutil.code_diff(base)
    try:
        with runtime.connect(config, fork=True) as safe:
            ctx = runtime.make_ctx(config, const)
            # --nonce overrides; else the Safe contract nonce (not AccountAPI.nonce).
            tx_nonce = nonce if nonce is not None else runtime.safe_onchain_nonce(safe)
            result = engine.simulate(
                fn,
                ctx,
                safe,
                network=config.network,
                safe_shortname=config.safe_shortname,
                execute=execute,
                nonce=tx_nonce,
            )
    except Exception as exc:  # never hang; surface a clear error
        _fail(f"dry-run failed: {exc}")

    block = render.render_block(result, diff=diff)
    click.echo(block)
    if post_comment:
        posted, msg = gitutil.post_comment(render.render_block(result))
        click.echo(f"post-comment: {msg}", err=not posted)
    if not result.success:
        _fail("pre-flight failed; see the simulation report above")


@main.command("send")
@_add_options
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt before proposing.")
@click.option("--label-pr", is_flag=True, help="Label the PR with '<network> #<nonce>'.")
@click.option(
    "--close-pr", is_flag=True, help="Label, close the PR, then delete its remote source branch."
)
@click.option("--notify", is_flag=True, help="Post a Telegram 'tx queued' message if configured.")
@click.option(
    "--reminder",
    is_flag=True,
    help="Open a re-evaluation issue on the PR, assigned to its author.",
)
@click.option(
    "--title", default=None, help="Telegram title (default: PR title, then @txn docstring)."
)
@click.option(
    "--description", default=None, help="Telegram description (default: PR body, then title)."
)
@click.option(
    "--sender", default=None, help="Telegram sender name (default: GITHUB_ACTOR/git user)."
)
@click.option(
    "--nonce",
    type=int,
    default=None,
    help="Override the Safe nonce — e.g. to REPLACE a tx already queued at that nonce.",
)
def send(
    fn_name,
    network,
    txs_file,
    constants_file,
    safe_address,
    rpc_uri,
    yes,
    label_pr,
    close_pr,
    notify,
    reminder,
    title,
    description,
    sender,
    nonce,
):  # noqa: ANN001
    """Simulate then propose the transaction to the Safe Tx Service via the delegate."""
    from safe_propose import engine, render, runtime
    from safe_propose.txservice import TxServiceError, resolve_endpoint

    config, fn, const = _resolve(fn_name, network, txs_file, constants_file, safe_address, rpc_uri)
    try:
        endpoint = resolve_endpoint(
            config.chain_id,
            gateway_api_key=config.gateway_api_key,
            timeout=config.request_timeout,
            override_url=config.tx_service_url,
        )
    except TxServiceError as exc:
        _fail(str(exc))

    try:
        # Pre-flight on a fork before touching the live node: calls are applied in batch
        # order (a withdraw funds a later transfer), which a live eth_call cannot do and a
        # live node must never persist. Abort if any call fails, so a failing tx is never
        # queued. Failing calls are shown with the same friendly trace line as the dry-run.
        with runtime.connect(config, fork=True) as fork_safe:
            fork_ctx = runtime.make_ctx(config, const)
            fork_batch = engine.build(fn, fork_ctx, fork_safe)
            preflighted_calls = engine.decode_calls(fork_batch)
            sims = engine.simulate_trace(fork_batch, fork_safe, require_ordered=True)
        failures = [c for c in sims if not c.success]
        if failures:
            detail = "\n  ".join(render.render_call_sim(c) for c in failures)
            _fail(f"pre-flight failed; not proposing:\n  {detail}")

        with runtime.connect(config, fork=False) as safe:
            ctx = runtime.make_ctx(config, const)
            batch = engine.build(fn, ctx, safe)  # rebuild on live for the proposed SafeTx
            # The definition may read mutable chain state, which can change between the
            # fork and live connections; never propose calls that were not pre-flighted.
            if engine.decode_calls(batch) != preflighted_calls:
                _fail(
                    "live batch differs from the pre-flighted fork batch (on-chain state "
                    "read by the definition changed); not proposing. Re-run send."
                )

            # --nonce overrides (to REPLACE a tx already queued at that nonce); otherwise
            # use the queue-aware "next" nonce from the Tx Service.
            override = nonce
            tx_nonce = override if override is not None else runtime.proposal_nonce(safe, endpoint)
            safe_tx, safe_tx_hash, proposed_nonce = engine.build_safe_tx(
                batch, safe, nonce=tx_nonce
            )
            if override is not None:
                click.echo(
                    f"note: overriding nonce to {proposed_nonce} — this REPLACES any tx already "
                    "queued at this nonce once enough owners sign.",
                    err=True,
                )

            # Print what the operator is about to queue so it can be verified in a wallet:
            # the full EIP-712 SafeTx message and payload.
            click.echo(
                render.render_signable(
                    safe_address=config.safe_address,
                    chain_id=config.chain_id,
                    tx_fields=engine.safe_tx_fields(safe_tx),
                    safe_tx_hash=safe_tx_hash,
                )
            )
            click.echo(f"nonce: {proposed_nonce}")
            service_kind = "override" if endpoint.is_override else "gateway"
            origin = endpoint.public_origin()
            origin_part = f" {origin}" if origin else ""
            click.echo(f"tx-service: {service_kind}{origin_part} (timeout={endpoint.timeout}s)")
            if not yes and not click.confirm("Propose this transaction to the Safe queue?"):
                _fail("aborted by user", code=2)

            proposer = runtime.load_proposer(config)
            runtime.propose(safe, safe_tx, endpoint, proposer)
    except Exception as exc:
        _fail(f"send failed: {exc}")

    click.echo(f"queue: {config.queue_url}")

    # Optional roboanimals-parity extras (Task 12) — never fail the send.
    pr_updated = True
    if label_pr or close_pr:
        from safe_propose.notify import label_pr as _label

        ok, msg = _label(config.safe_shortname, proposed_nonce, close=close_pr)
        pr_updated = ok
        if not ok:
            msg += "; PR update skipped or failed; transaction already queued; do not resend"
        click.echo(f"label-pr: {msg}", err=not ok)
    if notify and close_pr and not pr_updated:
        click.echo("notify: skipped because PR labeling or closure failed", err=True)
    elif notify:
        from safe_propose.notify import proposal_notification, transaction_url

        doc = (fn.__doc__ or "").strip()
        ok, msg = proposal_notification(
            config.safe_shortname,
            proposed_nonce,
            transaction_url(config.queue_url, safe_tx_hash),
            default_title=doc.splitlines()[0] if doc else fn.__name__,
            title=title,
            sender=sender,
            description=description,
        )
        click.echo(f"notify: {msg}", err=not ok)
    if reminder:
        from safe_propose.reminder import create_reminder_issue

        ok, msg = create_reminder_issue()
        click.echo(f"reminder: {msg}", err=not ok)
    if close_pr and pr_updated:
        from safe_propose.notify import delete_pr_branch

        ok, msg = delete_pr_branch()
        click.echo(f"delete-branch: {msg}", err=not ok)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
