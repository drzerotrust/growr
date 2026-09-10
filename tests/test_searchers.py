"""Dexscreener discovery and CLI failures without live requests."""

import json
from unittest.mock import Mock

import pytest
import requests

import growr
from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.http import HttpClient
from growr_cli.searchers import DexscreenerTokenSearcher


@pytest.mark.parametrize(
    ("flag", "search_type", "endpoint"),
    [
        ("--boosted", "boosted", "/token-boosts/latest/v1"),
        (
            "--community-takeovers",
            "community-takeovers",
            "/community-takeovers/latest/v1",
        ),
    ],
)
@pytest.mark.parametrize(
    "tokens", [[], [{"chainId": "solana", "tokenAddress": "mint"}]]
)
def test_discovery_cli_preserves_feed(
    monkeypatch, capsys, flag, search_type, endpoint, tokens
):
    get = Mock(return_value=Mock(ok=True, json=Mock(return_value=tokens)))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "--include-raw", "list", flag]
    )
    rpc = Mock(side_effect=AssertionError("Discovery must not use RPC"))
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)

    assert growr.main() == 0

    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["request"]["options"]["mode"] == search_type
    assert report["raw"]["discovery"] == tokens
    assert len(report["records"]) == len(tokens)
    for record in report["records"]:
        assert record["social"]["score"] == 0
    assert report["status"] == ("success" if tokens else "no_data")
    get.assert_called_once()
    assert get.call_args.args[0].endswith(endpoint)
    assert "/latest/dex/" not in get.call_args.args[0]
    assert get.call_args.kwargs["timeout"] > 0
    assert output.err == ""
    assert "\x1b" not in output.err
    rpc.assert_not_called()


@pytest.mark.parametrize("feed", ["--boosted", "--community-takeovers"])
@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("include_solana", [False, True])
def test_discovery_cli_lists_only_solana(
    monkeypatch, capsys, feed, json_mode, include_solana
):
    tokens = [
        {"chainId": "ethereum", "tokenAddress": "foreign-ethereum"},
        {"chainId": "base", "tokenAddress": "foreign-base"},
        {"tokenAddress": "unknown-chain"},
        {"chainId": None, "tokenAddress": "null-chain"},
    ]
    if include_solana:
        tokens.insert(1, {"chainId": "solana", "tokenAddress": "mint-first"})
        tokens.append({"chainId": "solana", "tokenAddress": "mint-second"})
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(return_value=Mock(ok=True, json=Mock(return_value=tokens))),
    )
    flags = ["--json"] if json_mode else ["--no-color"]
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "list", "dexscreener", feed]
    )

    assert growr.main() == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    for excluded in ("foreign-", "unknown-chain", "null-chain"):
        assert excluded not in captured.out
    if include_solana:
        assert captured.out.index("mint-first") < captured.out.index(
            "mint-second"
        )
    if json_mode:
        report = json.loads(captured.out)
        assert report["status"] == ("success" if include_solana else "no_data")
        assert len(report["records"]) == (2 if include_solana else 0)
        assert all(
            record["identity"]["chain"] == "solana"
            for record in report["records"]
        )


@pytest.mark.parametrize("payload", [None, {}, [None], ["mint"]])
def test_discovery_rejects_malformed_payload(monkeypatch, payload):
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(return_value=Mock(ok=True, json=Mock(return_value=payload))),
    )
    searcher = DexscreenerTokenSearcher(DexscreenerClient(HttpClient(5)))

    with pytest.raises(ValueError, match="unexpected response shape"):
        searcher.search(boosted=True)


@pytest.mark.parametrize("failure", ["transport", "http", "json"])
def test_discovery_failures_exit_without_exposing_secrets(
    monkeypatch, capsys, failure
):
    response = Mock(ok=True, status_code=503)
    get = Mock(return_value=response)
    if failure == "transport":
        get.side_effect = requests.Timeout("https://example?api-key=secret")
    elif failure == "http":
        response.ok = False
    else:
        response.json.side_effect = ValueError("secret response body")
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    monkeypatch.setattr("sys.argv", ["growr.py", "list", "--boosted"])

    assert growr.main() == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "Dexscreener" in output.err
    assert "secret" not in output.err


@pytest.mark.parametrize("options", [[], ["--on-chain"]])
def test_missing_discovery_mode_is_a_clear_cli_error(
    monkeypatch, capsys, options
):
    monkeypatch.setattr("sys.argv", ["growr.py", "list", *options])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)

    with pytest.raises(SystemExit) as error:
        growr.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "usage: growr list" in output.err
    assert "positional arguments:" in output.err
    assert "Missing provider: choose stonks or dexscreener" in output.err
    assert "python3 growr.py list stonks" in output.err
    assert "python3 growr.py --json list dexscreener" in output.err
    http.assert_not_called()
