"""Git/GitHub helpers: the PR code diff and posting a PR comment via ``gh``.

Every subprocess call is time-bounded (consistent with the no-hang invariant) and fails
soft: a missing ``git``/``gh``, no PR, or an unauthenticated CLI degrades to a warning,
never a crash or a hang.
"""

from __future__ import annotations

import os
import shutil
import subprocess

DEFAULT_TIMEOUT = 15
PR_ENV = "SAFE_PROPOSE_PR"


def _run(args: list[str], *, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Run a command with a timeout; return (returncode, stdout, stderr).

    Returns ``(127, "", msg)`` if the binary is missing and ``(124, "", msg)`` on timeout
    — never raises for the common failure modes.
    """
    if shutil.which(args[0]) is None:
        return 127, "", f"{args[0]} not found on PATH"
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} timed out after {timeout}s"


def detect_base(explicit: str | None = None) -> str:
    """Return the base ref for the diff: explicit, else origin's default, else main/master."""
    if explicit:
        return explicit
    # Try the remote's default branch (e.g. origin/main).
    code, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "origin/HEAD"])
    if code == 0 and out.strip():
        return out.strip()
    for candidate in ("main", "master"):
        code, _, _ = _run(["git", "rev-parse", "--verify", "--quiet", candidate])
        if code == 0:
            return candidate
    return "main"


def code_diff(base: str | None = None) -> str:
    """Return ``git diff <base>...HEAD`` for the consuming repo, or a note if unavailable."""
    ref = detect_base(base)
    code, out, err = _run(["git", "diff", f"{ref}...HEAD"])
    if code == 127 or code == 124:
        return f"(diff unavailable: {err})"
    if code != 0:
        # Fall back to a two-dot diff if the three-dot ref doesn't resolve.
        code, out, err = _run(["git", "diff", ref])
        if code != 0:
            return f"(diff unavailable: {err.strip() or 'git diff failed'})"
    return out


def detect_pr() -> str | None:
    """Return the PR number: ``SAFE_PROPOSE_PR`` (CI), else ``gh pr view`` on this HEAD."""
    explicit = os.environ.get(PR_ENV, "").strip()
    if explicit.isdigit():
        return explicit
    code, out, _ = _run(["gh", "pr", "view", "--json", "number", "-q", ".number"])
    if code == 0 and out.strip().isdigit():
        return out.strip()
    return None


def gh_pr_view_args(*args: str) -> list[str]:
    """``gh pr view`` argv, with an explicit PR number when detached HEAD cannot infer one."""
    cmd = ["gh", "pr", "view"]
    pr = detect_pr()
    if pr is not None:
        cmd.append(pr)
    cmd.extend(args)
    return cmd


def post_comment(body: str, *, pr: str | None = None) -> tuple[bool, str]:
    """Post ``body`` as a comment on the branch's PR via ``gh``.

    Returns ``(posted, message)``. Never raises: if ``gh`` is missing/unauthenticated or
    no PR is found, returns ``(False, <reason>)`` so the caller can warn and continue.
    """
    target = pr or detect_pr()
    if target is None:
        return False, "no PR found for the current branch (or gh unavailable)"
    code, _, err = _run(["gh", "pr", "comment", target, "--body", body], timeout=30)
    if code == 0:
        return True, f"posted comment to PR #{target}"
    return False, f"gh pr comment failed: {err.strip() or f'exit {code}'}"
