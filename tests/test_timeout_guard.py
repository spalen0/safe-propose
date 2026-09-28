"""Repo-wide guard: no HTTP call in our source omits a timeout (TEST_PLAN Layer 1).

This is the direct guard against the incident that motivated the repo. It is a static
check over ``src/`` for ``requests.<verb>(`` calls that do not pass ``timeout=``. The
engine mostly delegates HTTP to safe-eth-py (which we configure with an explicit
timeout), so this primarily protects future code that reaches for ``requests`` directly.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "safe_propose"

# requests.get( ... ) / requests.post( ... ) etc. Match the call up to its closing paren
# on the same logical line group (DOTALL across the argument list).
_CALL = re.compile(r"requests\.(get|post|put|patch|delete|head|request)\s*\((.*?)\)", re.S)


def test_no_untimed_requests_calls():
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        for match in _CALL.finditer(text):
            args = match.group(2)
            if "timeout" not in args:
                offenders.append(f"{path.name}: requests.{match.group(1)}(...) without timeout")
    assert not offenders, "untimed HTTP calls found:\n" + "\n".join(offenders)
