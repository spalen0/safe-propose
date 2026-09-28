"""Open a "re-evaluate this transaction" issue after a ``send`` (issue #9).

``send --reminder`` opens a GitHub issue on the current PR's repo, **assigned to the PR
author**, asking them to re-evaluate (and sign or cancel) the queued transaction. It is
strictly opt-in and fails soft (returns a status, never raises) so it can't break a send.

All ``gh`` calls go through the timeout-bounded :func:`safe_propose.gitutil._run`.
"""

from __future__ import annotations

import json

from safe_propose.gitutil import _run, detect_pr


def _pr_details(pr: str) -> dict | None:
    """Fetch number/author/title/url for ``pr`` via ``gh``, or None if unavailable."""
    code, out, _ = _run(["gh", "pr", "view", pr, "--json", "number,author,title,url"])
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _issue_body(pr: dict) -> str:
    number = pr["number"]
    pr_link = pr.get("url") or f"#{number}"
    return (
        f"#{number} proposed a Safe transaction.\n\n"
        "Please **re-evaluate** it before it is signed: re-read the diff, confirm the "
        "queued tx still reflects your intent, and then sign it (or cancel/replace it) in "
        "the Safe queue.\n\n"
        f"- PR: {pr_link}\n"
        f"- Title: {pr.get('title', '')}\n\n"
        "_Opened automatically by `safe-propose send --reminder`._"
    )


def create_reminder_issue(*, pr: str | None = None) -> tuple[bool, str]:
    """Open a re-evaluation issue for the branch's PR, assigned to its author.

    No-op (returns ``(False, reason)``) if no PR is found or ``gh`` is unavailable. If the
    author can't be assigned, the issue is still created and the author is @-mentioned.
    """
    target = pr or detect_pr()
    if target is None:
        return False, "no PR found to open a reminder for"
    details = _pr_details(target)
    if details is None:
        return False, f"could not read PR #{target} via gh"

    author = (details.get("author") or {}).get("login")
    title = f"Re-evaluate the Safe transaction from #{details['number']}"
    body = _issue_body(details)

    args = ["gh", "issue", "create", "--title", title, "--body", body]
    if author:
        args += ["--assignee", author]
    code, out, err = _run(args, timeout=30)
    if code != 0 and author:
        # Author may not be assignable; retry without the assignee, @-mentioning instead.
        code, out, err = _run(
            ["gh", "issue", "create", "--title", title, "--body", f"cc @{author}\n\n{body}"],
            timeout=30,
        )
    if code != 0:
        return False, f"reminder issue failed: {err.strip() or f'exit {code}'}"
    return True, f"opened reminder issue ({out.strip()})"
