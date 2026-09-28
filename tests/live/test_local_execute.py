"""Layer-3-style local MVP check: deploy a Safe and execute a tx on a local fork.

Marked ``live`` (deselected by default). Runs ``scripts/local_demo.py`` in a subprocess
(isolated Ape state) and asserts the demo executes a Safe tx end-to-end with no external
Tx Service. Skips cleanly without a Katana RPC or the ``anvil`` binary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

DEMO = Path(__file__).resolve().parents[2] / "scripts" / "local_demo.py"


@pytest.mark.skipif(
    not (os.environ.get("KATANA_RPC_2") or os.environ.get("KATANA_RPC")),
    reason="needs a Katana RPC env var",
)
@pytest.mark.skipif(shutil.which("anvil") is None, reason="needs the anvil binary (foundry)")
def test_local_demo_executes_safe_tx():
    src = str(Path(__file__).resolve().parents[2] / "src")
    proc = subprocess.run(
        [sys.executable, str(DEMO)],
        env={**os.environ, "PYTHONPATH": src},
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode == 2:
        pytest.skip(f"demo skipped: {proc.stdout.strip()}")
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "DEMO: OK" in proc.stdout
