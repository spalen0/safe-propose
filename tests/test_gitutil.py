"""Git helper tests (PR detection on detached SHA checkouts)."""

from __future__ import annotations

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
