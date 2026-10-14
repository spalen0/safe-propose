"""Live transaction output, bounded report capture, and interruption behavior."""

from __future__ import annotations

import selectors
import subprocess
import sys
from io import StringIO

import click
import pytest

from safe_propose.output import CAPTURE_LIMIT, capture_stdout


def test_output_is_redacted_and_visible_before_definition_finishes(monkeypatch, capsys):
    monkeypatch.setenv("KATANA_RPC", "https://keyhost.rpc.example/v2/secretkeyvalue")
    buffer = StringIO()
    with capture_stdout(buffer=buffer):
        print("host=", "keyhost.rpc.example", ", path=/v2/secretkeyvalue", sep="")
        assert capsys.readouterr().out == "host=***, path=/v2/***\n"
        print("continued", end="", flush=True)
        assert capsys.readouterr().out == "continued"
    assert capsys.readouterr().out == "\n"
    assert buffer.getvalue() == "host=***, path=/v2/***\ncontinued"


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(2), click.Abort()])
def test_interruptions_keep_output_and_restore_stdout(capsys, error):
    stream = sys.stdout
    buffer = StringIO()
    with pytest.raises(type(error)):
        with capture_stdout(buffer=buffer):
            print("before interrupt", end="")
            raise error
    assert sys.stdout is stream
    print("after interrupt")
    assert capsys.readouterr().out == "before interrupt\nafter interrupt\n"
    assert buffer.getvalue() == "before interrupt"


def test_report_capture_is_bounded_while_live_output_is_complete(capsys):
    buffer = StringIO()
    text = "x" * (CAPTURE_LIMIT * 20)
    with capture_stdout(buffer=buffer):
        print(text)
    assert capsys.readouterr().out == text + "\n"
    captured = buffer.getvalue()
    assert captured.startswith("x" * CAPTURE_LIMIT)
    assert "output truncated" in captured
    assert len(captured) < CAPTURE_LIMIT + 100


def test_stream_metadata_and_writelines_are_preserved(monkeypatch, capsys):
    monkeypatch.setenv("PROPOSER_PRIVATE_KEY", "secretkeyvalue")
    buffer = StringIO()
    stream = sys.stdout
    with capture_stdout(buffer=buffer):
        assert sys.stdout.encoding == stream.encoding
        assert sys.stdout.isatty() == stream.isatty()
        sys.stdout.writelines(["key=", "secretkeyvalue", "\n", "done\n"])
    assert capsys.readouterr().out == "key=***\ndone\n"
    assert buffer.getvalue() == "key=***\ndone\n"


def test_sigterm_keeps_already_printed_progress():
    script = (
        "from safe_propose.output import capture_stdout\n"
        "import time\n"
        "with capture_stdout():\n"
        "    print('progress before RPC')\n"
        "    time.sleep(30)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=5), "progress was not flushed before the stall"
            assert proc.stdout.readline() == "progress before RPC\n"
        proc.terminate()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
