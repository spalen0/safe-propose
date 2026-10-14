"""Git helper tests (PR detection on detached SHA checkouts)."""

from __future__ import annotations

import errno
import subprocess

import pytest

from safe_propose import gitutil


def test_detect_pr_prefers_safe_propose_pr_env(monkeypatch):
    monkeypatch.setenv("SAFE_PROPOSE_PR", "42")

    def fail(*a, **k):
        raise AssertionError("gh should not run")

    monkeypatch.setattr(gitutil, "_run", fail)
    assert gitutil.detect_pr() == "42"
    assert gitutil.gh_pr_view_args("--json", "number") == [
        "gh",
        "pr",
        "view",
        "42",
        "--json",
        "number",
    ]


def test_detect_pr_ignores_non_numeric_env(monkeypatch):
    monkeypatch.setenv("SAFE_PROPOSE_PR", "abc")
    monkeypatch.setattr(gitutil, "_run", lambda *a, **k: (0, "7\n", ""))
    assert gitutil.detect_pr() == "7"


@pytest.mark.parametrize("length", [40_000, 65_536])
def test_post_comment_uses_stdin_for_large_unicode_body(monkeypatch, length):
    body = "😀" * length
    monkeypatch.setattr("shutil.which", lambda command: command)

    def run(args, **kwargs):
        assert args == ["gh", "pr", "comment", "7", "--body-file", "-"]
        assert kwargs["input"] == body
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert gitutil.post_comment(body, pr="7") == (True, "posted comment to PR #7")


def test_oversized_report_fails_soft_without_posting(monkeypatch):
    def run(*args, **kwargs):
        pytest.fail("oversized report must not reach gh")

    monkeypatch.setattr(gitutil, "_run", run)
    posted, message = gitutil.post_comment("x" * 65_537, pr="7")
    assert not posted
    assert "65,536" in message and "terminal" in message


@pytest.mark.parametrize(
    "error", [OSError(errno.E2BIG, "Argument list too long"), PermissionError("permission denied")]
)
def test_post_comment_handles_subprocess_oserror(monkeypatch, error):
    monkeypatch.setattr("shutil.which", lambda command: command)

    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", run)
    posted, message = gitutil.post_comment("report", pr="7")
    assert not posted
    assert str(error) in message
