"""Workflow boundaries and ownership of network resources."""

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest

import growr
from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient


@pytest.mark.parametrize(
    ("command", "scanner_name"),
    [
        ("token", "TokenScanner"),
        ("wallet", "WalletScanner"),
        ("token-account", "TokenAccountScanner"),
    ],
)
@pytest.mark.parametrize("failure", [None, "scan", "render"])
def test_cli_closes_resources_on_success_and_failure(
    monkeypatch, command, scanner_name, failure
):
    http = Mock()
    rpc = Mock()
    scanner = Mock()
    renderer = Mock()
    monkeypatch.setattr(growr, "HttpClient", Mock(return_value=http))
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(growr, scanner_name, Mock(return_value=scanner))
    monkeypatch.setattr(growr, "renderer_for", Mock(return_value=renderer))
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            "--quiet",
            command,
            "So11111111111111111111111111111111111111112",
        ],
    )
    if failure == "scan":
        scanner.scan.side_effect = ValueError("scan failed")
    elif failure == "render":
        renderer.render.side_effect = ValueError("render failed")

    assert growr.main() == (1 if failure else 0)

    http.close.assert_called_once_with()
    rpc.close.assert_called_once_with()
    if failure == "scan":
        renderer.render.assert_not_called()
    else:
        renderer.render.assert_called_once()


def test_discovery_failure_closes_http_without_creating_rpc(monkeypatch):
    http = Mock()
    rpc_factory = Mock()
    searcher = Mock()
    searcher.search.side_effect = ValueError("discovery failed")
    monkeypatch.setattr(growr, "HttpClient", Mock(return_value=http))
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc_factory)
    monkeypatch.setattr(growr, "StonksSearcher", Mock(return_value=searcher))
    monkeypatch.setattr("sys.argv", ["growr.py", "--quiet", "list", "--stonk"])

    assert growr.main() == 1

    http.close.assert_called_once_with()
    rpc_factory.assert_not_called()


def test_http_owner_closes_the_session(monkeypatch):
    session = Mock()
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session",
        Mock(return_value=session),
    )
    http = HttpClient(5)

    http.close()

    session.close.assert_called_once_with()


@pytest.mark.parametrize("provider", ["jupiter", "dexscreener", "rugcheck"])
@pytest.mark.parametrize("outcome", ["success", "no_data", "failed"])
def test_single_provider_outcomes_retain_raw_data(provider, outcome):
    http = Mock()
    raw = {"id": "mint", "unrecognized_field": "preserved"}
    pair = {"chainId": "solana", "baseToken": {"address": "mint"}}
    clients = {
        "jupiter": JupiterClient(http, "test-key").get_token,
        "dexscreener": DexscreenerClient(http).get_pairs,
        "rugcheck": RugcheckClient(http).get_report,
    }
    payloads = {
        "jupiter": ([raw], raw),
        "dexscreener": ({"pairs": [pair]}, [pair]),
        "rugcheck": (raw, raw),
    }
    payload, expected = payloads[provider]
    if outcome != "success":
        payload = {
            "jupiter": [],
            "dexscreener": {"pairs": []},
            "rugcheck": None,
        }[provider]
    error = "HTTP 503" if outcome == "failed" else None
    http.get_json.return_value = (payload, error)

    result = clients[provider]("mint")

    assert result.status == outcome
    assert result.fetched_at
    if outcome == "success":
        assert result.data == expected
    if outcome == "failed":
        assert result.detail == error
    http.close.assert_not_called()


def test_unconfigured_jupiter_does_not_request_data():
    http = Mock()

    result = JupiterClient(http, None).get_token("mint")

    assert result.status == "not_configured"
    http.get_json.assert_not_called()


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("models.py", ("growr_cli",)),
        (
            "analysis",
            (
                "growr_cli.integrations",
                "growr_cli.scanners",
                "growr_cli.searchers",
                "growr_cli.enrichment",
                "growr_cli.solana",
            ),
        ),
        (
            "integrations",
            (
                "growr_cli.scanners",
                "growr_cli.searchers",
                "growr_cli.enrichment",
                "growr_cli.renderers",
                "growr",
            ),
        ),
        (
            "renderers",
            (
                "growr_cli.integrations",
                "growr_cli.scanners",
                "growr_cli.searchers",
                "growr_cli.enrichment",
                "growr_cli.solana",
            ),
        ),
    ],
)
def test_dependencies_follow_architecture(package, forbidden):
    root = Path(__file__).resolve().parents[1] / "growr_cli"
    target = root / package
    paths = [target] if target.is_file() else target.rglob("*.py")
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                modules = [module]
                modules.extend(
                    f"{module}.{alias.name}" for alias in node.names
                )
            else:
                continue
            assert not any(
                name == prefix or name.startswith(f"{prefix}.")
                for name in modules
                for prefix in forbidden
            ), f"{path.relative_to(root)} imports {modules}"
