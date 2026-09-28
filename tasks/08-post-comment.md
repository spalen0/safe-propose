# Task 08 — `--post-comment`

- depends on: 07
- parallel-safe: yes
- milestone: M2

## Goal
Mirror the roboanimals bot by posting the dry-run block to the PR.

## Steps
1. Detect the PR from the current branch via `gh pr view --json number` (or `gh pr list`).
2. Post the rendered block with `gh pr comment <pr> --body-file -`.
3. Graceful no-op with a warning if `gh` is missing/unauthenticated or no PR is found.
4. Reuse the exact rendered body from Task 07 (`render.py`) for the comment.

## Acceptance criteria
- [x] With a PR present, a comment is posted containing the diff + hash + link.
      `gitutil.post_comment` posts the **exact** rendered block via `gh pr comment`;
      `tests/test_cli.py::test_dry_run_post_comment` asserts the same body is reused.
- [x] Without `gh`/PR, the command still succeeds locally and warns clearly.
      `gitutil` fails soft (missing/timed-out binary, no PR) → `(False, reason)`; the CLI
      prints the warning to stderr and dry-run still exits 0.
