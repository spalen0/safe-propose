# Stdout review findings

## Fixed in PR #7

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

## Documented limits

- **Binary output bypasses capture and redaction:** delegated `sys.stdout.buffer` writes,
  including `click.echo(bytes)`, use the original stream rather than the text wrapper.
- **Secrets split across flushes can leak live:** redaction runs per emitted piece, so a
  complete secret assembled across flushes is masked only when the joined report is rendered.
- **Unflushed partial lines are lost on termination:** abrupt SIGTERM/SIGKILL termination
  does not unwind the Python context, leaving its pending partial line unflushed.
