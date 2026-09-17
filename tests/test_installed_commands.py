"""Installed commands, compatibility and private configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

import growr
from growr_cli import __version__, settings
from growr_cli.environment import environment_file, load_environment
from tests.test_token_screen import criteria, discovery, rule

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("GROWR_ENV_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("GROWR_TEST_VALUE", raising=False)
    monkeypatch.delenv("GROWR_TEST_COPY", raising=False)
    return tmp_path


def test_environment_file_precedence_and_interpolation(
    isolated_environment, monkeypatch
):
    root = isolated_environment
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    (root / ".env").write_text("GROWR_TEST_VALUE=checkout\n")
    assert environment_file(root)[1] == "checkout"
    explicit = root / "chosen.env"
    explicit.write_text(
        "GROWR_TEST_VALUE=from-file\nGROWR_TEST_COPY=${GROWR_TEST_VALUE}\n"
    )
    monkeypatch.setenv("GROWR_TEST_VALUE", "from-process")
    monkeypatch.chdir(root)
    monkeypatch.setenv("GROWR_ENV_FILE", "chosen.env")
    assert load_environment(root) == {"source": "explicit", "status": "loaded"}
    assert os.environ["GROWR_TEST_VALUE"] == "from-process"
    assert os.environ["GROWR_TEST_COPY"] == "from-process"
    assert os.environ["GROWR_ENV_FILE"] == str(explicit)


def test_installed_package_ignores_site_packages_and_cwd_dotenv(
    isolated_environment, monkeypatch
):
    root = isolated_environment
    installed = root / "site-packages"
    installed.mkdir()
    (installed / ".env").write_text("GROWR_TEST_VALUE=shared-secret\n")
    (root / ".env").write_text("GROWR_TEST_VALUE=working-secret\n")
    monkeypatch.chdir(root)
    assert load_environment(installed)["status"] == "not_selected"
    assert "GROWR_TEST_VALUE" not in os.environ
    folder = root / "config" / "growr"
    folder.mkdir(parents=True)
    (folder / ".env").write_text("GROWR_TEST_VALUE=user-config\n")
    assert load_environment(installed)["source"] == "user"
    assert os.environ["GROWR_TEST_VALUE"] == "user-config"


@pytest.mark.parametrize(
    "content",
    [
        None,
        b'PRIVATE="unterminated',
        b"\xff",
        b"PRIVATE=value\x00invalid",
        b"'PRIVATE=KEY'=value",
        b"''=value",
    ],
)
def test_bad_explicit_environment_is_safe(
    isolated_environment, monkeypatch, capsys, content
):
    root = isolated_environment
    path = root / "private.env"
    if content is not None:
        path.write_bytes(b"GROWR_TEST_VALUE=partial\n" + content)
    monkeypatch.setenv("GROWR_ENV_FILE", str(path))
    assert load_environment(root) == {
        "source": "explicit",
        "status": "invalid",
    }
    output = capsys.readouterr()
    assert output.out == output.err == ""
    assert "GROWR_TEST_VALUE" not in os.environ


def test_doctor_contracts_are_current_and_do_not_create_clients(
    monkeypatch, capsys
):
    blocked = Mock(side_effect=AssertionError("Doctor must stay offline"))
    monkeypatch.setattr(growr, "HttpClient", blocked)
    monkeypatch.setattr(growr, "SolanaRpcClient", blocked)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "private-jupiter-key")
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "private-helius-key")
    monkeypatch.setattr("sys.argv", ["growr", "doctor", "--json"])
    assert growr.main() == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["growr_version"] == __version__
    assert (
        report["contracts"]["cli"]
        == (growr.response_schema()["properties"]["schema_version"]["const"])
    )
    assert report["network_checked"] is False
    assert all(report["playbooks"].values())
    assert "private-" not in output.out
    assert output.err == ""
    blocked.assert_not_called()


@pytest.mark.parametrize(
    "option,value,error",
    [
        ("--min-version", "99.0.0", "growr_version_below_minimum"),
        ("--max-version", "0.3.0", "growr_version_at_or_above_maximum"),
        ("--require-cli-schema", "99", "cli_contract_mismatch"),
        ("--require-playbook-version", "99", "playbook_contract_mismatch"),
        ("--require-screening-version", "99", "screening_contract_mismatch"),
    ],
)
def test_doctor_rejects_incompatible_consumers(
    monkeypatch, capsys, option, value, error
):
    monkeypatch.setattr(
        "sys.argv", ["growr", "--json", "doctor", option, value]
    )
    assert growr.main() == 1
    assert error in json.loads(capsys.readouterr().out)["errors"]


@pytest.mark.parametrize("json_before", [True, False])
def test_packaged_screen_dispatch_preserves_offline_json(
    monkeypatch, tmp_path, capsys, json_before
):
    source = tmp_path / "discovery.json"
    source.write_text(json.dumps(discovery(liquidity=100)))
    config = tmp_path / "criteria.json"
    config.write_text(json.dumps(criteria(rule("liquidity_usd", 50))))
    blocked = Mock(side_effect=AssertionError("Replay must stay offline"))
    monkeypatch.setattr("growr_cli.playbooks.runner.subprocess.run", blocked)
    options = ["--criteria", str(config), "--input", str(source)]
    prefix = ["--json"] if json_before else []
    suffix = [] if json_before else ["--json"]
    monkeypatch.setattr(
        "sys.argv",
        ["growr", *prefix, "playbook", "token-screen", *options, *suffix],
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["counts"]["matched"] == 1
    assert result["budget"]["subprocesses_attempted"] == 0
    assert output.err == ""
    blocked.assert_not_called()


@pytest.mark.parametrize(
    "flag",
    [["--rpc-url", "https://example.invalid"], ["--max-rpc-calls", "1"]],
)
def test_playbook_does_not_silently_ignore_global_controls(monkeypatch, flag):
    monkeypatch.setattr(
        "sys.argv", ["growr", *flag, "playbook", "activity", "--help"]
    )
    with pytest.raises(SystemExit) as error:
        growr.main()
    assert error.value.code == 2


def test_module_and_script_entry_points_agree(tmp_path):
    for entry in (["-m", "growr_cli"], [str(ROOT / "growr.py")]):
        result = subprocess.run(
            [sys.executable, *entry, "--version"],
            cwd=ROOT if entry[0] == "-m" else tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "growr %s" % __version__
        assert result.stderr == ""
