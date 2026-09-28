"""Optional roboanimals-parity notifications after a successful ``send`` (Task 12).

Two features, both **strictly opt-in and no-op when unconfigured** — they never fail a
send:
  * label the PR with ``<network> #<nonce>`` and optionally close it, and
  * post a "new tx queued" message to a Telegram chat, with a clickable link to the Safe
    queue so signers can review + sign.

All network calls are time-bounded (Telegram via ``requests`` with a timeout; ``gh`` via
the timeout-bounded helpers in :mod:`safe_propose.gitutil`).

Telegram setup:
  * ``TELEGRAM_TOKEN`` — a bot token from @BotFather. The bot must be a member of the chat.
  * ``TELEGRAM_CHAT_ID`` — the target chat/group id (negative for groups, e.g.
    ``-1001234567890``). For a group, get it from ``getUpdates`` or @RawDataBot.
"""

from __future__ import annotations

import html
import json
import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from safe_propose.gitutil import _run, detect_pr, gh_pr_view_args

TELEGRAM_TIMEOUT = 10


def label_pr(
    network: str, nonce: int, *, pr: str | None = None, close: bool = False
) -> tuple[bool, str]:
    """Label the branch's PR with ``"<network> #<nonce>"`` and optionally close it.

    The label is created if missing (pinned color/description). An existing label is
    reused as-is rather than ``--force``-updated, which would recolor it.

    Args:
        network: Network shortname used in the label.
        nonce: Nonce of the successfully proposed transaction.
        pr: Explicit PR number, otherwise detect the current branch's PR.
        close: Close the PR after its label is successfully applied.

    Returns:
        Success and a status message. GitHub failures leave the proposal unaffected.
    """
    target = pr or detect_pr()
    if target is None:
        return False, "no PR to label"
    label = f"{network} #{nonce}"
    # Create if missing. Do not use ``--force``: it recolors/rewrites an existing
    # label. A name collision is success — the label is already there to apply.
    code, out, err = _run(
        [
            "gh",
            "label",
            "create",
            label,
            "--color",
            "0E8A16",
            "--description",
            f"Safe transaction nonce {nonce} on {network}",
        ]
    )
    if code != 0 and "already exists" not in f"{out}\n{err}".lower():
        return False, f"label creation failed: {err.strip() or out.strip() or f'exit {code}'}"
    code, _, err = _run(["gh", "pr", "edit", target, "--add-label", label])
    if code != 0:
        return False, f"label failed: {err.strip() or f'exit {code}'}"
    message = f"labeled PR #{target} '{label}'"
    if close:
        code, _, err = _run(["gh", "pr", "close", target])
        if code != 0:
            return False, f"{message}; close failed: {err.strip() or f'exit {code}'}"
        message += "; closed PR"
    return True, message


def delete_pr_branch() -> tuple[bool, str]:
    """Delete the closed PR's remote source branch after notification steps finish.

    Returns:
        Success and a diagnostic. Fork branches and the default branch are never deleted.
    """
    code, out, err = _run(gh_pr_view_args("--json", "state,headRefName,isCrossRepository"))
    if code != 0:
        return False, f"branch lookup failed: {err.strip() or f'exit {code}'}"
    try:
        pr = json.loads(out)
        if pr["state"] != "CLOSED" or pr["isCrossRepository"] is not False:
            return False, "branch deletion skipped: PR must be closed and in the same repository"
        branch = pr["headRefName"]
        if not isinstance(branch, str) or not branch:
            raise ValueError("missing source branch")
    except (ValueError, KeyError, TypeError):
        return False, "branch deletion skipped: invalid PR metadata"
    code, out, err = _run(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"])
    if code != 0:
        return False, f"repository lookup failed: {err.strip() or f'exit {code}'}"
    try:
        repo = json.loads(out)
        default_branch = repo["defaultBranchRef"]["name"]
        name = repo["nameWithOwner"]
        if not isinstance(default_branch, str) or not isinstance(name, str) or not name:
            raise ValueError("invalid repository")
        if branch == default_branch:
            return False, "branch deletion skipped: source is the default branch"
    except (ValueError, KeyError, TypeError):
        return False, "branch deletion skipped: invalid repository metadata"
    code, _, err = _run(
        ["gh", "api", f"repos/{name}/git/refs/heads/{quote(branch, safe='')}", "--method", "DELETE"]
    )
    if code != 0:
        return False, f"branch deletion failed: {err.strip() or f'exit {code}'}"
    return True, f"deleted remote branch '{branch}'"


def detect_sender(env: dict[str, str] | None = None) -> str:
    """Best-effort author name: ``GITHUB_ACTOR`` (CI) → ``git config user.name`` → 'unknown'."""
    env = env if env is not None else dict(os.environ)
    actor = env.get("GITHUB_ACTOR")
    if actor:
        return actor
    code, out, _ = _run(["git", "config", "user.name"])
    if code == 0 and out.strip():
        return out.strip()
    return "unknown"


def queued_message(
    network: str,
    nonce: int,
    url: str,
    *,
    title: str,
    sender: str,
    description: str,
    pr_url: str | None = None,
) -> str:
    """Build the Telegram message with separate code, output, and signing links.

    Mirrors the roboanimals notification, e.g.::

        ✍️ katana #20 "add new weeth/usdc market and update katana caps"
        Sender: "alice"
        Description: "add new weeth/usdc market and update katana caps"
        Review the code, verify the output, and view queued tx on safe

    Dynamic text is HTML-escaped so titles/descriptions can't break the markup.
    """
    t = html.escape(title)
    s = html.escape(sender)
    d = html.escape(description)
    link = html.escape(url, quote=True)
    review_links = "Review the code, verify the output, "
    if pr_url:
        files_link = html.escape(pr_url + "/files", quote=True)
        output_link = html.escape(pr_url, quote=True)
        review_links = (
            f'<a href="{files_link}">Review the code</a>, '
            f'<a href="{output_link}">verify the output</a>, '
        )
    return (
        f'✍️ {html.escape(network)} #{nonce} "{t}"\n'
        f'Sender: "{s}"\n'
        f'Description: "{d}"\n'
        f'{review_links}and <a href="{link}">view queued tx on safe</a>'
    )


def transaction_url(queue_url: str, safe_tx_hash: str) -> str:
    """Link to the proposed Safe transaction, retaining custom queue URLs as a fallback.

    Args:
        queue_url: Configured queue URL containing the Safe's shortname and address.
        safe_tx_hash: Hash of the successfully proposed Safe transaction.

    Returns:
        A transaction detail URL for the standard Safe route, otherwise the queue URL.
    """
    url = urlsplit(queue_url)
    path = url.path.rstrip("/")
    query = dict(parse_qsl(url.query))
    safe = query.get("safe", "")
    if not path.endswith("/transactions/queue") or ":" not in safe:
        return queue_url
    query["id"] = f"multisig_{safe.split(':', 1)[1]}_{safe_tx_hash}"
    return urlunsplit(
        url._replace(path=path.removesuffix("/queue") + "/tx", query=urlencode(query))
    )


def proposal_notification(
    network: str,
    nonce: int,
    url: str,
    *,
    default_title: str,
    title: str | None = None,
    description: str | None = None,
    sender: str | None = None,
) -> tuple[bool, str]:
    """Read the branch's PR metadata and notify Telegram after a successful proposal.

    Args:
        network: Network shortname.
        nonce: Proposed nonce.
        url: Safe transaction link.
        default_title: Function docstring or name when no PR metadata is available.
        title: Optional title override.
        description: Optional description override.
        sender: Optional sender override, otherwise use the invoking actor.

    Returns:
        Notification status, including a diagnostic if PR metadata was unavailable.
    """
    code, out, err = _run(gh_pr_view_args("--json", "title,body,url"))
    details = {}
    diagnostic = ""
    try:
        if code != 0:
            raise ValueError(err.strip() or f"gh exited {code}")
        details = json.loads(out)
        if not isinstance(details, dict) or not all(
            isinstance(details.get(key), str) for key in ("title", "body", "url")
        ):
            raise ValueError("invalid PR metadata")
    except ValueError as exc:
        details = {}
        diagnostic = f"PR metadata unavailable ({exc}); using function metadata; "
    msg_title = title or details.get("title") or default_title
    body = queued_message(
        network,
        nonce,
        url,
        title=msg_title,
        sender=sender or detect_sender(),
        description=description or details.get("body", "").strip() or msg_title,
        pr_url=details.get("url") or None,
    )
    ok, message = telegram_notify(body)
    return ok, diagnostic + message


def telegram_notify(
    message: str,
    *,
    parse_mode: str = "HTML",
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Post ``message`` to Telegram if ``TELEGRAM_TOKEN`` + ``TELEGRAM_CHAT_ID`` are set.

    No-op (returns ``(False, reason)``) when unconfigured. ``parse_mode`` defaults to HTML
    so a 'sign here' link renders; link previews are disabled to keep the message compact.
    The HTTP call carries a timeout.
    """
    env = env if env is not None else dict(os.environ)
    token = env.get("TELEGRAM_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False, "telegram not configured (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID)"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=TELEGRAM_TIMEOUT,
        )
        if resp.status_code == 200:
            return True, "telegram notified"
        body = _redact_secret(resp.text, token, limit=120)
        return False, f"telegram HTTP {resp.status_code}: {body}"
    except requests.RequestException as exc:
        return False, f"telegram error: {_redact_secret(str(exc), token)}"


def _redact_secret(text: str, secret: str, *, limit: int | None = None) -> str:
    """Strip ``secret`` from an error string so bot tokens never appear in CLI output.

    Redact the full string first, then optionally truncate. Slicing first can leave a
    token prefix that no longer matches ``secret`` and would leak into the CLI.
    """
    cleaned = text.replace(secret, "***") if secret else text
    return cleaned[:limit] if limit is not None else cleaned
