"""Static checks that CI and the reference workflow keep their security guardrails."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / ".github" / "workflows" / "safe-propose.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _run_scripts(text: str) -> list[str]:
    """Return the bodies of YAML ``run: |`` / ``run: |-`` blocks."""
    scripts: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped in {"run: |", "run: |-"}:
            indent = len(lines[i]) - len(lines[i].lstrip())
            i += 1
            body: list[str] = []
            while i < len(lines):
                line = lines[i]
                if line.strip() == "":
                    body.append(line)
                    i += 1
                    continue
                if len(line) - len(line.lstrip()) <= indent:
                    break
                body.append(line)
                i += 1
            scripts.append("\n".join(body))
            continue
        i += 1
    return scripts


def test_ci_is_read_only_and_does_not_persist_credentials():
    text = CI.read_text()
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    for script in _run_scripts(text):
        assert "${{" not in script


def test_example_workflow_does_not_persist_credentials():
    text = EXAMPLE.read_text()
    assert text.count("persist-credentials: false") >= 2


def test_example_workflow_requires_same_repo_pr_and_pins_sha():
    text = EXAMPLE.read_text()
    assert "head_repo_id" in text and "base_repo_id" in text
    assert "Only PR branches in this repository can run with secrets." in text
    assert "ref: ${{ steps.pr.outputs.sha }}" in text
    assert "Confirm verified PR commit" in text
    assert "IFS=$'\\t'" in text
    assert '.head.repo.id // "null"' in text
    assert "send=true requires sha=" in text
    assert "comment_sha" in text
    assert "collaborators/${ACTOR}/permission" in text
    assert "SAFE_PROPOSE_PR" in text
    assert "tr -d '\\r'" in text
    assert '--base "origin/${DEFAULT_BRANCH}"' in text
    assert "if [ -f requirements.txt ]; then" in text
    assert "<<:" not in text
    assert "*network_secrets" not in text
    assert "git fetch" not in text
    assert "PROPOSER_PRIVATE_KEY: ${{ secrets.PROPOSER_PRIVATE_KEY }}" in text
    deps = text[text.index("Install consuming-repo deps") :]
    deps_step = deps.split("- name:", 1)[0]
    assert "|| true" not in deps_step


def test_example_workflow_installs_engine_before_pr_checkout():
    text = EXAMPLE.read_text()
    assert text.index("Install engine") < text.index("Check out verified PR commit")
    assert text.index("Install consuming-repo deps") > text.index("Check out verified PR commit")
    install_step = text.split("- name: Install engine", 1)[1].split("- name:", 1)[0]
    assert "SAFE_PROPOSE_REF: ${{ vars.SAFE_PROPOSE_REF }}" in install_step
    guard = 'if [[ ! "$SAFE_PROPOSE_REF" =~ ^[0-9a-f]{40}$ ]]; then'
    install = 'python -m pip install "safe-propose'
    assert install_step.index(guard) < install_step.index("exit 1") < install_step.index(install)
    deps_step = text.split("- name: Install consuming-repo deps", 1)[1].split("- name:", 1)[0]
    assert "SAFE_PROPOSE_REF: ${{ vars.SAFE_PROPOSE_REF }}" in deps_step
    pin_check = 'distribution("safe-propose").read_text("direct_url.json")'
    assert deps_step.index("pip install -r requirements.txt") < deps_step.index(pin_check)


def test_engine_install_brings_fork_provider():
    # The workflow installs only the pinned engine before the PR checkout; dry-run and
    # send fork through ape-foundry, so it must be a runtime dependency, not a PR's choice.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert any(dep.startswith("ape-foundry") for dep in project["dependencies"])


def _run_engine_install(tmp_path: Path, ref: str) -> subprocess.CompletedProcess:
    """Run the Install engine step with a fake ``python`` that logs its arguments."""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nprintf 'pip called: %s\\n' \"$*\"\n")
    python.chmod(0o755)
    install_step = EXAMPLE.read_text().split("- name: Install engine", 1)[1].split("- name:", 1)[0]
    script = _run_scripts(install_step)[0]
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SAFE_PROPOSE_REF": ref,
    }
    return subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_example_workflow_rejects_invalid_engine_ref_before_pip(tmp_path):
    result = _run_engine_install(tmp_path, "not-a-commit")
    assert result.returncode != 0
    assert "Set SAFE_PROPOSE_REF" in result.stdout
    assert "pip called" not in result.stdout


def test_example_workflow_installs_pinned_engine_from_public_url(tmp_path):
    sha = "ab" * 20
    result = _run_engine_install(tmp_path, sha.upper())
    assert result.returncode == 0, result.stderr
    assert f"safe-propose @ git+https://github.com/spalen0/safe-propose.git@{sha}" in result.stdout


def test_example_workflow_passes_inputs_via_env_and_quotes_them():
    text = EXAMPLE.read_text()
    assert 'fn="$INPUT_FN"' in text
    assert 'network="$INPUT_NETWORK"' in text
    assert 'send="$INPUT_SEND"' in text
    assert 'safe-propose dry-run --fn "$FN" --network "$NETWORK"' in text
    assert 'safe-propose send --fn "$FN" --network "$NETWORK"' in text
    assert r"^[A-Za-z_][A-Za-z0-9_]*$" in text
    for script in _run_scripts(text):
        assert "${{" not in script, script
