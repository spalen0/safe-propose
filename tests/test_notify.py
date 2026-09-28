"""Unit tests for optional parity notifications (Task 12)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from safe_propose import notify


def test_telegram_noop_when_unconfigured():
    ok, msg = notify.telegram_notify("hi", env={})
    assert ok is False
    assert "not configured" in msg


def test_telegram_posts_when_configured(monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200

    def fake_post(url, json, timeout):  # noqa: A002 - mirror requests signature
        sent.update(url=url, json=json, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    ok, msg = notify.telegram_notify(
        "queued", env={"TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "-1001234567890"}
    )
    assert ok is True
    assert sent["timeout"] == notify.TELEGRAM_TIMEOUT  # call is time-bounded
    assert sent["json"]["chat_id"] == "-1001234567890"
    assert sent["json"]["parse_mode"] == "HTML"  # so the 'sign here' link renders


def test_queued_message_format_and_escaping():
    msg = notify.queued_message(
        "katana",
        20,
        "https://app.safe.global/transactions/queue?safe=katana:0x90D0",
        title="add new weeth/usdc market and update katana caps",
        sender="alice",
        description="add new weeth/usdc market and update katana caps",
        pr_url="https://github.com/yearn/example/pull/5",
    )
    assert msg.startswith('✍️ katana #20 "add new weeth/usdc market and update katana caps"')
    assert 'Sender: "alice"' in msg
    assert 'Description: "add new weeth/usdc market' in msg
    assert '<a href="https://github.com/yearn/example/pull/5/files">Review the code</a>' in msg
    assert '<a href="https://github.com/yearn/example/pull/5">verify the output</a>' in msg
    assert 'safe=katana:0x90D0">view queued tx on safe</a>' in msg

    # Dynamic text is HTML-escaped so a title can't break the markup.
    escaped = notify.queued_message(
        "katana", 1, "https://x", title="a <b> & c", sender="m", description="d"
    )
    assert "&lt;b&gt;" in escaped and "&amp;" in escaped and "<b>" not in escaped
    assert 'and <a href="https://x">view queued tx on safe</a>' in escaped


@pytest.mark.parametrize("trailing_slash", ["", "/"])
def test_transaction_link_identifies_proposed_hash(trailing_slash):
    url = notify.transaction_url(
        f"https://app.safe.global/transactions/queue{trailing_slash}?safe=eth:0xSafe&theme=dark",
        "0xHash",
    )
    assert urlsplit(url).path == "/transactions/tx"
    assert parse_qs(urlsplit(url).query) == {
        "safe": ["eth:0xSafe"],
        "id": ["multisig_0xSafe_0xHash"],
        "theme": ["dark"],
    }


@pytest.mark.parametrize(
    "url", ["https://custom/home?safe=rise:0xSafe", "https://x/transactions/queue"]
)
def test_custom_transaction_link_falls_back_to_queue(url):
    assert notify.transaction_url(url, "0xHash") == url


@pytest.mark.parametrize("overrides", [False, True])
def test_proposal_notification_uses_pr_metadata(monkeypatch, overrides):
    monkeypatch.setattr(
        notify,
        "_run",
        lambda args: (
            0,
            '{"title":"set flow caps to 0 for oeth","body":"oeth/usdc market",'
            '"url":"https://github.com/yearn/example/pull/110"}',
            "",
        ),
    )
    monkeypatch.setenv("GITHUB_ACTOR", "alice")
    messages = []
    monkeypatch.setattr(
        notify, "telegram_notify", lambda body: (messages.append(body) or True, "sent")
    )
    kwargs = dict(title="override", description="custom", sender="alice") if overrides else {}
    ok, _ = notify.proposal_notification("eth", 53, "https://safe/tx", default_title="fn", **kwargs)
    assert ok
    assert (
        f'✍️ eth #53 "{"override" if overrides else "set flow caps to 0 for oeth"}"' in messages[0]
    )
    assert 'Sender: "alice"' in messages[0]
    assert f'Description: "{"custom" if overrides else "oeth/usdc market"}"' in messages[0]
    assert 'pull/110/files">Review the code</a>' in messages[0]


@pytest.mark.parametrize(
    "response", [(124, "", "timeout"), (0, "invalid", ""), (0, "null", ""), (0, '{"title": 3}', "")]
)
def test_metadata_failure_falls_back_with_diagnostic(monkeypatch, response):
    monkeypatch.setattr(notify, "_run", lambda args: response)
    messages = []
    monkeypatch.setattr(
        notify, "telegram_notify", lambda body: (messages.append(body) or True, "sent")
    )
    ok, msg = notify.proposal_notification(
        "eth", 53, "https://safe/tx", default_title="fn", sender="m"
    )
    assert ok
    assert "PR metadata unavailable" in msg
    assert 'Description: "fn"' in messages[0]


def test_empty_pr_body_uses_title_and_escapes_links(monkeypatch):
    monkeypatch.setattr(
        notify,
        "_run",
        lambda args: (
            0,
            '{"title":"a <b> & c","body":"  ","url":"https://github.com/o/r/pull/1"}',
            "",
        ),
    )
    messages = []
    monkeypatch.setattr(
        notify,
        "telegram_notify",
        lambda body: (messages.append(body) or False, "telegram HTTP 400"),
    )
    ok, msg = notify.proposal_notification(
        "eth", 0, "https://safe/tx?safe=x&id=y", default_title="fn", sender="a & b"
    )
    assert not ok
    assert msg == "telegram HTTP 400"
    assert 'Description: "a &lt;b&gt; &amp; c"' in messages[0]
    assert 'Sender: "a &amp; b"' in messages[0]
    assert 'href="https://safe/tx?safe=x&amp;id=y"' in messages[0]


def test_detect_sender_prefers_github_actor():
    assert notify.detect_sender(env={"GITHUB_ACTOR": "alice"}) == "alice"


def test_telegram_errors_redact_bot_token(monkeypatch):
    class _Resp:
        status_code = 401
        text = "unauthorized bot SECRETTOKEN leaked"

    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: _Resp())
    ok, msg = notify.telegram_notify(
        "x", env={"TELEGRAM_TOKEN": "SECRETTOKEN", "TELEGRAM_CHAT_ID": "-1"}
    )
    assert ok is False
    assert "SECRETTOKEN" not in msg
    assert "***" in msg

    def boom(*a, **k):
        raise notify.requests.ConnectionError(
            "Failed to connect to https://api.telegram.org/botSECRETTOKEN/sendMessage"
        )

    monkeypatch.setattr(notify.requests, "post", boom)
    ok, msg = notify.telegram_notify(
        "x", env={"TELEGRAM_TOKEN": "SECRETTOKEN", "TELEGRAM_CHAT_ID": "-1"}
    )
    assert ok is False
    assert "SECRETTOKEN" not in msg


def test_telegram_redacts_before_truncating(monkeypatch):
    token = "UNIQUE_BOT_TOKEN_XYZ"

    # Token starts after the 120-char cut, so slicing first would leak a prefix
    # that no longer equals ``token`` and would skip redaction.
    class _Resp:
        status_code = 400
        text = "n" * 110 + token

    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: _Resp())
    ok, msg = notify.telegram_notify("x", env={"TELEGRAM_TOKEN": token, "TELEGRAM_CHAT_ID": "-1"})
    assert ok is False
    assert token not in msg
    assert "UNIQUE_BOT" not in msg
    assert "***" in msg


def test_label_pr_noop_without_pr(monkeypatch):
    monkeypatch.setattr(notify, "detect_pr", lambda: None)
    ok, msg = notify.label_pr("katana", 19)
    assert ok is False
    assert "no PR" in msg


@pytest.mark.parametrize("close", [False, True])
def test_label_pr_labels(monkeypatch, close):
    monkeypatch.setattr(notify, "detect_pr", lambda: "5")
    captured = []
    monkeypatch.setattr(notify, "_run", lambda args: captured.append(args) or (0, "", ""))
    ok, msg = notify.label_pr("katana", 19, close=close)
    assert ok is True
    assert captured[:2] == [
        [
            "gh",
            "label",
            "create",
            "katana #19",
            "--color",
            "0E8A16",
            "--description",
            "Safe transaction nonce 19 on katana",
        ],
        ["gh", "pr", "edit", "5", "--add-label", "katana #19"],
    ]
    assert captured[2:] == ([["gh", "pr", "close", "5"]] if close else [])


def test_label_pr_reuses_existing_label(monkeypatch):
    monkeypatch.setattr(notify, "detect_pr", lambda: "5")
    captured = []

    def run(args):
        captured.append(args)
        if args[:3] == ["gh", "label", "create"]:
            return (1, "", "label 'katana #19' already exists; use `--force` to update it")
        return (0, "", "")

    monkeypatch.setattr(notify, "_run", run)
    ok, msg = notify.label_pr("katana", 19)
    assert ok is True
    assert "labeled PR #5" in msg
    assert captured[1] == ["gh", "pr", "edit", "5", "--add-label", "katana #19"]


@pytest.mark.parametrize("failure_step", [1, 2, 3])
@pytest.mark.parametrize("error", ["permission denied", "gh timed out after 15s", ""])
def test_pr_update_stops_on_failure(monkeypatch, failure_step, error):
    calls = []

    def run(args):
        calls.append(args)
        return (1, "", error) if len(calls) == failure_step else (0, "", "")

    monkeypatch.setattr(notify, "_run", run)
    ok, msg = notify.label_pr("eth", 0, pr="110", close=True)
    assert not ok
    assert len(calls) == failure_step
    assert (error or "exit 1") in msg
    assert "failed" in msg


@pytest.mark.parametrize(
    "state,fork,branch,deleted",
    [
        ("CLOSED", False, "feature/tx", True),
        ("OPEN", False, "feature/tx", False),
        ("CLOSED", True, "feature/tx", False),
        ("CLOSED", False, "main", False),
    ],
)
def test_branch_cleanup_targets_only_closed_same_repo_pr(monkeypatch, state, fork, branch, deleted):
    calls = []

    def run(args):
        calls.append(args)
        if args[1] == "pr":
            return (
                0,
                json.dumps({"state": state, "isCrossRepository": fork, "headRefName": branch}),
                "",
            )
        if args[1] == "repo":
            return 0, '{"nameWithOwner":"o/r","defaultBranchRef":{"name":"main"}}', ""
        return 0, "", ""

    monkeypatch.setattr(notify, "_run", run)
    ok, _ = notify.delete_pr_branch()
    assert ok == deleted
    assert [call for call in calls if call[1] == "api"] == (
        [["gh", "api", "repos/o/r/git/refs/heads/feature%2Ftx", "--method", "DELETE"]]
        if deleted
        else []
    )


@pytest.mark.parametrize("step", [1, 2, 3])
@pytest.mark.parametrize("malformed", [False, True])
def test_branch_cleanup_reports_errors(monkeypatch, step, malformed):
    calls = []
    responses = [
        (0, '{"state":"CLOSED","isCrossRepository":false,"headRefName":"feature"}', ""),
        (0, '{"nameWithOwner":"o/r","defaultBranchRef":{"name":"main"}}', ""),
        (0, "", ""),
    ]
    responses[step - 1] = (0, "null", "") if malformed and step < 3 else (1, "", "denied")

    def run(args):
        calls.append(args)
        return responses[len(calls) - 1]

    monkeypatch.setattr(notify, "_run", run)
    ok, msg = notify.delete_pr_branch()
    assert not ok
    assert len(calls) == step
    assert "invalid" in msg or "denied" in msg
