"""Unit tests for the re-evaluation reminder (issue #9)."""

from __future__ import annotations

import json

from safe_propose import reminder

_PR = {
    "number": 9,
    "author": {"login": "bob"},
    "title": "queue a tx",
    "url": "https://github.com/o/r/pull/9",
}


def _patch_gh(monkeypatch, *, view_rc=0, create_rc=0, create_out="issue-url"):
    """Patch reminder._run; record calls and fake gh outputs. Returns the call log."""
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["gh", "pr", "view"]:
            return view_rc, (json.dumps(_PR) if view_rc == 0 else ""), ""
        if args[:3] == ["gh", "issue", "create"]:
            return create_rc, create_out, "" if create_rc == 0 else "boom"
        return 0, "", ""

    monkeypatch.setattr(reminder, "_run", fake_run)
    return calls


def test_noop_without_pr(monkeypatch):
    monkeypatch.setattr(reminder, "detect_pr", lambda: None)
    ok, msg = reminder.create_reminder_issue()
    assert ok is False
    assert "no PR" in msg


def test_creates_issue_assigned_to_author(monkeypatch):
    monkeypatch.setattr(reminder, "detect_pr", lambda: "9")
    calls = _patch_gh(monkeypatch)
    ok, msg = reminder.create_reminder_issue()
    assert ok is True
    assert "issue-url" in msg
    create = next(c for c in calls if c[:3] == ["gh", "issue", "create"])
    assert "--assignee" in create and "bob" in create  # assigned to the PR author
    body = create[create.index("--body") + 1]
    assert "#9" in body and "re-evaluate" in body.lower()


def test_falls_back_when_assignee_rejected(monkeypatch):
    monkeypatch.setattr(reminder, "detect_pr", lambda: "9")
    attempts: list[list[str]] = []

    def fake_run(args, **kwargs):
        if args[:3] == ["gh", "pr", "view"]:
            return 0, json.dumps(_PR), ""
        if args[:3] == ["gh", "issue", "create"]:
            attempts.append(args)
            if "--assignee" in args:
                return 1, "", "user is not assignable"
            return 0, "issue-url", ""
        return 0, "", ""

    monkeypatch.setattr(reminder, "_run", fake_run)
    ok, msg = reminder.create_reminder_issue()
    assert ok is True
    assert len(attempts) == 2  # retried without the assignee
    body = attempts[1][attempts[1].index("--body") + 1]
    assert "@bob" in body  # author is @-mentioned instead


def test_returns_error_when_pr_unreadable(monkeypatch):
    monkeypatch.setattr(reminder, "detect_pr", lambda: "9")
    _patch_gh(monkeypatch, view_rc=1)
    ok, msg = reminder.create_reminder_issue()
    assert ok is False
    assert "could not read PR" in msg
