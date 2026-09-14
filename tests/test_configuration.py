"""Startup settings validation, fallback and credential-safe logging."""

import json
from unittest.mock import Mock

import pytest
from dotenv import dotenv_values

import growr
from growr_cli import settings
from growr_cli.configuration import log_configuration
from growr_cli.logger import configure_console_logging
from tests.test_machine import validate


def arguments(*command):
    """Build validated options without starting network clients."""

    parser = growr.build_parser()
    args = parser.parse_args(command)
    growr._validate_search_arguments(parser, args)
    return args


def test_default_configuration_explains_public_services(monkeypatch, capsys):
    monkeypatch.setattr(settings, "HELIUS_API_KEY", None)
    monkeypatch.setattr(settings, "CUSTOM_RPC_URL", None)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", None)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_VALUE", None)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 15.0)
    for name in (
        "PUBLIC_SOLANA_RPC_URL",
        "STONKS_API_URL",
    ):
        default = getattr(settings, "DEFAULT_%s" % name).rstrip("/")
        monkeypatch.setattr(settings, name, default)
    configure_console_logging(enabled=True, use_color=False)
    log_configuration(
        arguments("list", "stonks", "--on-chain"),
        settings.PUBLIC_SOLANA_RPC_URL,
        None,
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert "public Solana fallback" in output.err
    assert "default https://api.mainnet-beta.solana.com" in output.err
    assert "default 15.0 seconds" in output.err
    assert "JUPITER_API_KEY: unset" in output.err
    assert "not_configured" in output.err


def test_custom_urls_and_keys_never_appear_in_logs(monkeypatch, capsys):
    secret = "sensitive-key-never-log"
    endpoint = "https://user:password@private.example/%s?key=%s" % (
        secret,
        secret,
    )
    for name in ("HELIUS_API_KEY", "JUPITER_API_KEY"):
        monkeypatch.setattr(settings, name, secret)
    for name in (
        "HELIUS_MAINNET_RPC_URL",
        "STONKS_API_URL",
        "JUPITER_API_URL",
    ):
        monkeypatch.setattr(settings, name, endpoint)
    configure_console_logging(enabled=True, use_color=False)
    log_configuration(
        arguments("list", "stonks", "--on-chain"), endpoint, None
    )
    output = capsys.readouterr()
    assert "configured (hidden)" in output.err
    for value in (secret, "private.example", "password", endpoint):
        assert value not in output.out + output.err


@pytest.mark.parametrize(
    ("name", "value", "command"),
    [
        ("JUPITER_API_KEY", "your_jupiter_api_key", ["list", "stonks"]),
        ("STONKS_API_URL", "invalid-private-value", ["list", "stonks"]),
        (
            "STONKS_API_URL",
            "invalid-private-value",
            ["search", "stonks", "te"],
        ),
        (
            "JUPITER_API_URL",
            "https://host:99999",
            ["list", "jupiter"],
        ),
        (
            "JUPITER_API_URL",
            "https://host:99999",
            ["search", "jupiter", "JUP"],
        ),
        (
            "JUPITER_API_KEY",
            "your_jupiter_api_key",
            ["search", "jupiter", "JUP"],
        ),
    ],
)
def test_invalid_active_configuration_fails_before_http(
    monkeypatch, capsys, name, value, command
):
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "synthetic-key")
    monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", *command])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    validate(report)
    assert report["error"]["code"] == "EXECUTION_FAILED"
    assert name in report["error"]["message"]
    assert value not in output.out + output.err
    http.assert_not_called()


@pytest.mark.parametrize(
    "command", [["list", "jupiter"], ["search", "jupiter", "JUP"]]
)
def test_unused_rpc_credentials_do_not_block_jupiter_discovery(
    monkeypatch, command
):
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "synthetic-key")
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "your_helius_api_key")
    log_configuration(arguments(*command), "bad-unused-rpc", None)


@pytest.mark.parametrize("value", ["inf", "nan", "-1", "private-invalid"])
def test_bad_timeout_uses_announced_finite_default(monkeypatch, capsys, value):
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_VALUE", value)
    timeout = settings._timeout_seconds(value)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", timeout)
    assert timeout == 15.0
    configure_console_logging(enabled=True, use_color=False)
    log_configuration(arguments("list", "stonks"), None, None)
    output = capsys.readouterr()
    assert "Invalid REQUEST_TIMEOUT_SECONDS; using default 15.0" in output.err
    assert value not in output.err


def test_example_can_be_copied_without_enabling_placeholder_credentials():
    example = dotenv_values(settings.PROJECT_ROOT / ".env.example")
    for name in ("HELIUS_API_KEY", "JUPITER_API_KEY", "SOLANA_RPC_URL"):
        assert example[name] == ""
