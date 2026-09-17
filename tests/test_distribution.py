"""Build, inspect and execute the wheel outside the checkout."""

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from tests.test_token_screen import criteria, discovery, rule

ROOT = Path(__file__).resolve().parents[1]


def run_command(arguments, cwd, environment=None):
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def installed_distribution(tmp_path_factory):
    root = tmp_path_factory.mktemp("growr-distribution")
    output = root / "dist"
    run_command(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(output),
        ],
        ROOT,
    )
    wheel = next(output.glob("*.whl"))
    target = root / "installed"
    run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-cache-dir",
            "--target",
            str(target),
            str(wheel),
        ],
        root,
    )
    config = root / "empty.env"
    config.write_text("")
    environment = dict(
        os.environ,
        PYTHONPATH=str(target),
        GROWR_ENV_FILE=str(config),
    )
    return root, output, target, environment


def test_archives_exclude_local_files_and_other_repositories(
    installed_distribution,
):
    _, output, _, _ = installed_distribution
    with zipfile.ZipFile(next(output.glob("*.whl"))) as wheel:
        names = wheel.namelist()
        assert "growr.py" in names
        assert "growr_cli/playbooks/token_screen.py" in names
        assert "growr_cli/playbooks/runner.py" in names
        for name in names:
            assert (
                name == "growr.py"
                or (name.startswith("growr_cli/") and name.endswith(".py"))
                or ".dist-info/" in name
            ), name
    forbidden = {
        "skills",
        ".agents",
        ".codex",
        "docs",
        "data",
        "webapp",
        "tests",
        "scripts",
        "client.py",
        ".env",
        "AGENTS.md",
        "REFERENCES.md",
    }
    with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
        for member in archive.getmembers():
            relative = Path(member.name).parts[1:]
            assert not set(relative) & forbidden, member.name
            assert not any(part.startswith(".env") for part in relative)


def test_installed_console_module_and_children_resolve_packaged_code(
    installed_distribution,
):
    root, _, target, environment = installed_distribution
    # Verify imports resolve to the installed wheel.
    code = (
        "from pathlib import Path; import growr; "
        "assert Path(growr.__file__).parent == Path(%r); "
        "from growr_cli.playbooks.runner import GrowrRunner; "
        "runner = GrowrRunner(10, 1); "
        "runner.capture(['token', 'invalid'], lambda value: value, 1, 1, 10); "
        "assert runner.scans[0]['returncode'] == 2"
    ) % str(target)
    run_command([sys.executable, "-c", code], root, environment)
    for command in (
        [str(target / "bin" / "growr")],
        [sys.executable, "-m", "growr_cli"],
    ):
        result = run_command(
            [*command, "doctor", "--json", "--require-cli-schema", "2.2"],
            root,
            environment,
        )
        report = json.loads(result.stdout)
        assert report["status"] == "success"
        assert report["network_checked"] is False
        assert result.stderr == ""
    for name in (
        "token-screen",
        "token-holders",
        "wallet-holdings",
        "shared-holdings",
        "activity",
    ):
        result = run_command(
            [str(target / "bin" / "growr"), "playbook", name, "--help"],
            root,
            environment,
        )
        assert "--json" in result.stdout


def test_installed_playbook_replays_saved_evidence(installed_distribution):
    root, _, target, environment = installed_distribution
    (root / "criteria.json").write_text(
        json.dumps(criteria(rule("liquidity_usd", 50)))
    )
    (root / "evidence.json").write_text(json.dumps(discovery(liquidity=100)))
    result = run_command(
        [
            str(target / "bin" / "growr"),
            "playbook",
            "token-screen",
            "--criteria",
            "criteria.json",
            "--input",
            "evidence.json",
            "--json",
        ],
        root,
        environment,
    )
    report = json.loads(result.stdout)
    assert report["counts"]["matched"] == 1
    assert report["budget"]["subprocesses_attempted"] == 0
    assert result.stderr == ""
