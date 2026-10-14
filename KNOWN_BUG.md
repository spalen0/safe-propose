# Triaged findings

The following findings from the stdout review are fixed in PR #7:

- **Hidden progress and lost interruption diagnostics:** buffering all definition stdout
  until simulation ended hid progress, while the replay handler excluded `BaseException`.
- **Large PR comments could crash dry-run:** comment bodies were passed as one command
  argument, subprocess OS errors propagated, and report output had no size budget.
- **Raw definition stdout on send:** `send` called `build` directly, bypassing the
  capture/redaction applied only by `simulate`.
- **Merged CLI error lines:** replaying captured output without a terminal newline could
  merge the final definition print with the greppable `error:` prefix.
- **Empty transaction-output sections:** whitespace-only stdout was checked by truthiness
  instead of testing for nonblank text.
