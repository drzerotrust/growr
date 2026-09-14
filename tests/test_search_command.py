"""Query discovery and candidate selection without RPC scans."""

import json
from unittest.mock import Mock

import pytest

import growr
from growr_cli import settings
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import validate

TOKENS = [
    {"id": OTHER, "name": "Jupiter Candidate", "symbol": "JUP"},
    {
        "id": MINT,
        "name": "Jupiter",
        "symbol": "JUP",
        "usdPrice": 0,
        "website": "https://project.example",
        "twitter": "https://x.com/project",
        "analytics": {"on_chain": {"status": "success", "data": {}}},
    },
]


@pytest.fixture
def search_io(monkeypatch):
    """Keep the workflow real and forbid scan dependencies."""

    monkeypatch.setattr(settings, "JUPITER_API_KEY", "synthetic-key")
    monkeypatch.setattr(
        settings, "JUPITER_API_URL", settings.DEFAULT_JUPITER_API_URL
    )
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_VALUE", "5")
    # Irrelevant provider settings must not prevent a Jupiter query.
    for name in ("RPC_URL", "STONKS_API_URL", "RUGCHECK_API_URL"):
        monkeypatch.setattr(settings, name, "invalid-unused-endpoint")
    get = Mock(return_value=Mock(ok=True, json=Mock(return_value=TOKENS)))
    close = Mock()
    monkeypatch.setattr("requests.Session.get", get)
    monkeypatch.setattr("requests.Session.close", close)
    forbidden = Mock(
        side_effect=AssertionError("Search must only use Jupiter")
    )
    for name in (
        "SolanaRpcClient",
        "TokenScanner",
        "TokenContext",
        "RugcheckClient",
        "StonksClient",
        "OnChainEnricher",
    ):
        monkeypatch.setattr(growr, name, forbidden)
    yield get, close
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("JUP", [OTHER, MINT]),
        ("  Jupiter Candidate  ", [OTHER, MINT]),
        (MINT, [MINT]),
        ("%s,%s" % (MINT, OTHER), [OTHER, MINT]),
        ("11111111111111111111111111111111", []),
    ],
)
def test_search_returns_candidates_without_selecting_or_scanning(
    monkeypatch, capsys, search_io, query, expected
):
    get, close = search_io
    monkeypatch.setattr(
        "sys.argv",
        ["growr.py", "--json", "--include-raw", "search", "jupiter", query],
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    document = validate(json.loads(output.out))
    assert output.err == ""
    assert document["request"] == {
        "command": "search",
        "target": None,
        "options": {
            "source": "jupiter",
            "mode": "search",
            "query": query.strip(),
            "include_raw": True,
        },
        "rpc": None,
    }
    assert document["status"] == ("success" if expected else "no_data")
    assert [
        item["identity"]["mint"] for item in document["records"]
    ] == expected
    assert document["raw"]["discovery"] == TOKENS
    assert document["pagination"] is None
    assert all(item["source"] == "jupiter" for item in document["coverage"])
    for record in document["records"]:
        assert record["kind"] == "token_discovery"
        assert record["on_chain"] is None
        assert record["facts"]["source"] == "jupiter"
        if record["identity"]["mint"] == MINT:
            assert record["metrics"]["jupiter"]["values"]["price_usd"] == 0
            assert record["social"]["score"] == 80
    get.assert_called_once_with(
        "%s/search" % settings.JUPITER_API_URL,
        params={"query": query.strip()},
        headers={"x-api-key": "synthetic-key"},
        timeout=5,
    )
    close.assert_called_once()


def test_console_search_shows_names_mints_and_social_links(
    monkeypatch, capsys, search_io
):
    monkeypatch.setattr("sys.argv", ["growr.py", "search", "jupiter", "JUP"])
    assert growr.main() == 0
    output = capsys.readouterr()
    for text in ("Jupiter search", "Jupiter Candidate", MINT, OTHER, "80/100"):
        assert text in output.out
    assert "https://project.example" in output.out
    assert "On-chain observations" not in output.out
    assert output.err == ""


def test_failed_search_closes_http_and_keeps_structured_error(
    monkeypatch, capsys, search_io
):
    get, close = search_io
    get.return_value.json.return_value = {"error": "private provider message"}
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "search", "jupiter", "JUP"]
    )
    assert growr.main() == 1
    output = capsys.readouterr()
    document = validate(json.loads(output.out))
    assert document["error"]["code"] == "EXECUTION_FAILED"
    assert document["records"] == []
    assert document["request"]["command"] == "search"
    assert document["request"]["rpc"] is None
    assert "private provider message" not in output.out + output.err
    assert output.err == ""
    get.assert_called_once()
    close.assert_called_once()


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["jupiter"],
        ["unknown", "JUP"],
        ["jupiter", ""],
        ["jupiter", "  "],
        ["jupiter", "JUP,USDC"],
        ["jupiter", "%s," % MINT],
        ["jupiter", ",".join([MINT] * 101)],
        ["jupiter", "JUP", "--on-chain"],
        ["jupiter", "JUP", "--jupiter-search", "recent"],
        ["jupiter", "JUP", "--interval", "1h"],
        ["jupiter", "JUP", "--limit", "1"],
        ["jupiter", "JUP", "--stonk"],
        ["jupiter", "JUP", "--page", "1"],
        ["jupiter", "JUP", "--sort", "marketCap"],
        ["jupiter", "JUP", "--page-size", "30"],
        ["jupiter", "JUP", "--category", "xstock"],
    ],
)
def test_invalid_search_arguments_fail_before_network(
    monkeypatch, capsys, arguments, json_mode
):
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr("sys.argv", ["growr.py", *flags, "search", *arguments])
    http = Mock()
    rpc = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    if json_mode:
        assert growr.main() == 2
    else:
        with pytest.raises(SystemExit) as error:
            growr.main()
        assert error.value.code == 2
    output = capsys.readouterr()
    if json_mode:
        document = validate(json.loads(output.out))
        assert document["error"]["code"] == "INVALID_ARGUMENTS"
        assert document["request"]["options"] == {}
        assert output.err == ""
    else:
        assert output.out == ""
        if arguments in ([], ["jupiter"]):
            assert "usage: growr search" in output.err
            assert "positional arguments:" in output.err
            assert "python3 growr.py search jupiter JUP" in output.err
            assert "python3 growr.py --json token <MINT>" in output.err
    http.assert_not_called()
    rpc.assert_not_called()
