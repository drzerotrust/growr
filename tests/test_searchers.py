"""Jupiter discovery contracts and failures without live requests."""

import json
from contextlib import closing
from unittest.mock import Mock

import pytest
import requests

import growr
from growr_cli import settings
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.searchers import JupiterTokenSearcher
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import validate


@pytest.fixture(autouse=True)
def jupiter_key(monkeypatch):
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "synthetic-key")


@pytest.mark.parametrize(
    ("command", "mode", "path", "params"),
    [
        (["list", "jupiter"], "recent", "/recent", {}),
        (["search", "jupiter", "JUP"], "search", "/search", {"query": "JUP"}),
        (["search", "jupiter", MINT], "search", "/search", {"query": MINT}),
        (
            ["list", "jupiter", "--jupiter-search", "toptraded"],
            "toptraded",
            "/toptraded/24h",
            {"limit": 50},
        ),
        (
            [
                "list",
                "jupiter",
                "--jupiter-search",
                "toptrending",
                "--interval",
                "5m",
                "--limit",
                "10",
            ],
            "toptrending",
            "/toptrending/5m",
            {"limit": 10},
        ),
        (
            ["list", "jupiter", "--jupiter-search", "toporganicscore"],
            "toporganicscore",
            "/toporganicscore/24h",
            {"limit": 50},
        ),
    ],
)
@pytest.mark.parametrize("tokens", [[], [{"id": MINT, "usdPrice": 0}]])
def test_discovery_cli_preserves_feed(
    monkeypatch, capsys, command, mode, path, params, tokens
):
    get = Mock(return_value=Mock(ok=True, json=Mock(return_value=tokens)))
    monkeypatch.setattr("requests.Session.get", get)
    monkeypatch.setattr(
        "sys.argv",
        ["growr.py", "--json", "--include-raw", *command],
    )
    rpc = Mock(side_effect=AssertionError("Discovery must not use RPC"))
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    assert growr.main() == 0
    output = capsys.readouterr()
    report = validate(json.loads(output.out))
    assert report["request"]["options"]["mode"] == mode
    assert report["raw"]["discovery"] == tokens
    assert report["status"] == ("success" if tokens else "no_data")
    assert len(report["records"]) == len(tokens)
    for record in report["records"]:
        assert record["identity"]["chain"] == "solana"
        assert record["metrics"]["jupiter"]["values"]["price_usd"] == 0
        assert record["social"]["score"] == 0
    get.assert_called_once()
    call = get.call_args
    assert call.args[0] == "%s%s" % (settings.JUPITER_API_URL, path)
    assert call.kwargs["params"] == params
    assert call.kwargs["headers"] == {"x-api-key": "synthetic-key"}
    assert call.kwargs["timeout"] > 0
    assert output.err == ""
    rpc.assert_not_called()


@pytest.mark.parametrize("query", [MINT, "%s,%s" % (MINT, OTHER)])
@pytest.mark.parametrize("wrong_id", ["wrong", None, []])
def test_mint_queries_reject_nearby_hits_and_preserve_raw(query, wrong_id):
    tokens = [{"id": wrong_id, "symbol": MINT}, {"id": MINT}]
    client = Mock(discover=Mock(return_value=tokens))
    report = JupiterTokenSearcher(client).search("search", query=query)
    assert [item["id"] for item in report.findings.tokens] == [MINT]
    assert report.raw == tokens


@pytest.mark.parametrize("payload", [None, {}, [None], ["mint"]])
def test_discovery_rejects_malformed_payload(monkeypatch, payload):
    monkeypatch.setattr(
        "requests.Session.get",
        Mock(return_value=Mock(ok=True, json=Mock(return_value=payload))),
    )
    with closing(HttpClient(5)) as http:
        searcher = JupiterTokenSearcher(JupiterClient(http, "synthetic-key"))
        with pytest.raises(ValueError, match="unexpected response shape"):
            searcher.search()


@pytest.mark.parametrize("failure", ["transport", "http", "json"])
@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "command", [["list", "jupiter"], ["search", "jupiter", "JUP"]]
)
def test_discovery_failures_exit_without_exposing_secrets(
    monkeypatch, capsys, failure, json_mode, command
):
    response = Mock(ok=True, status_code=503)
    get = Mock(return_value=response)
    if failure == "transport":
        get.side_effect = requests.Timeout("https://example?api-key=secret")
    elif failure == "http":
        response.ok = False
    else:
        response.json.side_effect = ValueError("secret response body")
    monkeypatch.setattr("requests.Session.get", get)
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr("sys.argv", ["growr.py", *flags, *command])
    assert growr.main() == 1
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    if json_mode:
        assert validate(json.loads(output.out))["status"] == "error"
        assert output.err == ""
    else:
        assert output.out == ""
        assert "Run failed:" in output.err
        assert "Jupiter" in output.err


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
    assert "Missing provider: choose stonks or jupiter" in output.err
    assert "python3 growr.py list stonks" in output.err
    assert "python3 growr.py --json list jupiter" in output.err
    http.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        ["--query", "JUP"],
        ["--interval", "5m"],
        ["--limit", "1"],
        ["--jupiter-search", "toptraded", "--limit", "101"],
        ["--jupiter-search", "toptraded", "--limit", "0"],
    ],
)
def test_invalid_discovery_options_fail_before_clients(
    monkeypatch, capsys, options
):
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "list", "jupiter", *options]
    )
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 2
    assert (
        validate(json.loads(capsys.readouterr().out))["error"]["code"]
        == "INVALID_ARGUMENTS"
    )
    http.assert_not_called()


@pytest.mark.parametrize(
    "command", [["list", "jupiter"], ["search", "jupiter", "JUP"]]
)
def test_discovery_requires_key_before_network(monkeypatch, capsys, command):
    monkeypatch.setattr(settings, "JUPITER_API_KEY", None)
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", *command])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 1
    assert (
        "JUPITER_API_KEY"
        in validate(json.loads(capsys.readouterr().out))["error"]["message"]
    )
    http.assert_not_called()
