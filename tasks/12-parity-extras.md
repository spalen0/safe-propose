# Task 12 — Parity extras (optional)

- depends on: 09
- parallel-safe: yes
- milestone: M3

## Goal
Optional features to reach feature-parity with roboanimals notifications/labels.

## Steps
1. PR nonce label: after `send`, label the PR with `<network> #<nonce>` (via `gh`),
   matching roboanimals' tagging so a queued tx is traceable to its PR.
2. Telegram notification: optional, behind `TELEGRAM_TOKEN` + chat id config; post the
   "new tx queued" message used today. The chat id lives in the consuming repo's env
   (`TELEGRAM_CHAT_ID`), not in this engine.
3. Keep both strictly optional and no-op when unconfigured.

## Acceptance criteria
- [x] After successful PR closure and notification/reminder attempts, delete its remote
      source branch; skip fork/default branches and report failures without resending.
- [x] Telegram uses the PR title/body, invoking actor, and separate code/output/signing
      links; `--close-pr --notify` sends only after successful proposal and PR closure.
- [x] `send --close-pr` creates/applies the nonce label and closes the PR only after
      successful pre-flight and proposal; label failures prevent closure.
- [x] `send` optionally labels the PR and/or posts to Telegram when configured.
      `safe_propose/notify.py` (`label_pr`, `queued_message`, `telegram_notify`); wired as
      `send --label-pr` / `send --notify` (+ `--title`/`--description`/`--sender`). Telegram
      uses `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID`, timeout-bounded, HTML message with a
      clickable code/output/signing links (title/description default to PR metadata,
      falling back to the `@txn` docstring; sender defaults to `GITHUB_ACTOR`/git user).
- [x] Unconfigured → silently skipped, no errors. Both return `(False, reason)` and the
      CLI only warns; covered by `tests/test_notify.py`.
