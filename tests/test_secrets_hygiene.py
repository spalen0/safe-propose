"""Guard against tracking local secret files and known operational identifiers."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("-" + "5090" + "872581", "52" + "LE")
_SKIP_NAMES = frozenset({"uv.lock"})
_SKIP_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".pyc", ".so", ".whl"})

# Values that are configuration, not secrets, and may appear after `=` in .env.example.
_ENV_EXAMPLE_ALLOW_VALUES = frozenset({"SAFE_TRANSACTION_SERVICE_REQUEST_TIMEOUT"})


def _git_paths(*args: str) -> list[Path]:
    """Return NUL-separated paths from ``git ls-files`` (tracked files only)."""
    proc = subprocess.run(
        ["git", "ls-files", "-z", *args],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace")[:200]
        raise RuntimeError(f"git ls-files failed ({proc.returncode}): {err}")
    return [Path(raw.decode()) for raw in proc.stdout.split(b"\0") if raw]


def _iter_text_files():
    """Yield tracked text files. Ignored/untracked local secret files are never read."""
    for relative in _git_paths():
        path = ROOT / relative
        if not path.is_file() or path.name in _SKIP_NAMES:
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        yield path


def _is_ignored(path: str) -> bool:
    """Apply the repository .gitignore rules to ``path``, tracked or not."""
    proc = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if proc.returncode not in (0, 1):
        err = proc.stderr.decode(errors="replace")[:200]
        raise RuntimeError(f"git check-ignore failed ({proc.returncode}): {err}")
    return proc.returncode == 0


def test_no_ignored_files_tracked():
    # .gitignore is the single source of truth for local secret files (.env, keyfiles,
    # .ape/, ...); a tracked file matching it was force-added.
    tracked = [str(path) for path in _git_paths("--cached", "--ignored", "--exclude-standard")]
    assert not tracked, "ignored (local secret) files tracked:\n" + "\n".join(tracked)


def test_gitignore_covers_secret_files():
    for path in (
        ".env",
        "dev.env",
        "nested/.env.local",
        "secrets.json",
        "cert.pem",
        "deploy.key",
        ".ape/keyfile.json",
        ".ape/accounts/proposer.json",
    ):
        assert _is_ignored(path), path
    for path in (".env.example", "examples/.env.example", "sub/.env.example"):
        assert not _is_ignored(path), path


def test_hygiene_scan_uses_tracked_files_only(monkeypatch, tmp_path):
    tracked = tmp_path / "readme.md"
    tracked.write_text("ok")
    (tmp_path / ".env").write_text("ignored")

    def fake_run(args, **kwargs):
        assert args[:2] == ["git", "ls-files"]
        assert kwargs.get("timeout")
        return subprocess.CompletedProcess(args, 0, stdout=b"readme.md\0", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(f"{__name__}.ROOT", tmp_path)
    assert list(_iter_text_files()) == [tracked]


def test_no_operational_secrets_in_tree():
    hits: list[str] = []
    for path in _iter_text_files():
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in FORBIDDEN:
            if needle in content:
                hits.append(str(path.relative_to(ROOT)))
    assert not hits, "operational identifiers found in:\n" + "\n".join(hits)


def test_env_example_values_are_empty():
    path = ROOT / "examples" / ".env.example"
    filled: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.split("#", 1)[0].strip()
        if key.strip() in _ENV_EXAMPLE_ALLOW_VALUES:
            continue
        if value:
            filled.append(f"{key.strip()}={value}")
    assert not filled, "examples/.env.example must not ship filled values:\n" + "\n".join(filled)
