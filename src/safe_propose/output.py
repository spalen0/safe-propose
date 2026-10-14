"""Stream redacted Python stdout live and retain a bounded copy for reports."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Generator, Iterable
from io import StringIO
from typing import Any, TextIO

from safe_propose.config import redact_error_text

CAPTURE_LIMIT = 16_000
_TRUNCATED = "\n[transaction output truncated; full output is in the process log]\n"


class _TransactionStdout:
    """Buffer partial Python writes so a printed line is redacted before streaming."""

    def __init__(self, stream: TextIO, buffer: StringIO | None) -> None:
        self._stream = stream
        self._buffer = buffer
        self._pending = ""
        self._line_open = False
        self._truncated = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def write(self, text: str) -> int:
        """Consume Python text writes and emit complete lines immediately."""
        lines = (self._pending + text).split("\n")
        self._pending = lines.pop()
        for line in lines:
            self._emit(line + "\n")
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def _emit(self, text: str) -> None:
        text = redact_error_text(text)
        self._stream.write(text)
        self._stream.flush()
        self._line_open = not text.endswith("\n")
        if self._buffer is not None:
            remaining = max(0, CAPTURE_LIMIT - self._buffer.tell())
            self._buffer.write(text[:remaining])
            self._truncated |= len(text) > remaining

    def flush(self) -> None:
        """Honor explicit print flushes, including a partial line."""
        if self._pending:
            self._emit(self._pending)
            self._pending = ""
        self._stream.flush()

    def finish(self) -> None:
        """Flush on every exit and separate subsequent CLI output onto a new line."""
        self.flush()
        if self._line_open:
            self._stream.write("\n")
            self._stream.flush()
        if self._truncated and self._buffer is not None:
            self._buffer.write(_TRUNCATED)


@contextlib.contextmanager
def capture_stdout(*, buffer: StringIO | None = None) -> Generator[None, None, None]:
    """Stream redacted definition output, optionally retaining a bounded report copy.

    Args:
        buffer: Destination for redacted text, limited to CAPTURE_LIMIT characters
            plus a truncation notice. Native writes to FD 1 are not captured.

    Yields:
        Control while Python stdout writes are redirected; stderr stays unchanged.
    """
    stream = _TransactionStdout(sys.stdout, buffer)
    with contextlib.redirect_stdout(stream):
        try:
            yield
        finally:
            stream.finish()
