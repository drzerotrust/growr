"""Stonks query requests, candidate records and provider isolation."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests

import growr
from growr_cli import settings
from growr_cli.integrations.stonks import StonksClient
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import validate

DATA = {
    "tokens": [
        {"mint": OTHER, "pool": "pool-a", "name": "Server candidate"},
        {
            "mint": MINT,
            "pool": "pool-b",
            "name": "Test token",
            "symbol": "TEST",
            "market": {"priceUsd": 0, "marketCapUsd": 80, "volume24hUsd": 30},
            "links": {
                "website": "https://project.example",
                "twitter": "https://x.com/project",
            },
            "analytics": {
                "on_chain": {"status": "success", "data": {"forged": True}},
                "jupiter": {"status": "success", "data": {"forged": True}},
            },
        },
        {"mint": MINT, "pool": "pool-c", "symbol": "TEST"},
    ],
    "featured": {"mint": MINT, "pool": "featured-only"},
    "pagination": {"page": 3, "pageSize": 5, "total": 33, "totalPages": 7},
    "generatedAt": "2026-09-12T16:00:00Z",
    "source": "provider-market-data",
}


ENVELOPE = {"data": DATA, "meta": {"generatedAt": "2026-09-12T16:00:00Z"}}


@pytest.fixture
def stonks_io(monkeypatch):
    """Allow Stonks HTTP only, with unusable unrelated settings."""

    monkeypatch.setattr(
        settings, "STONKS_API_URL", settings.DEFAULT_STONKS_API_URL.rstrip("/")
    )
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_VALUE", "5")
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "your_jupiter_api_key")
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "your_helius_api_key")
    for name in ("RPC_URL", "JUPITER_API_URL", "RUGCHECK_API_URL"):
        monkeypatch.setattr(settings, name, "invalid-unused-setting")
    get = Mock(
        return_value=Mock(
            ok=True,
            status_code=200,
            json=Mock(return_value=deepcopy(ENVELOPE)),
        )
    )
    close = Mock()
    monkeypatch.setattr("requests.Session.get", get)
    monkeypatch.setattr("requests.Session.close", close)
    forbidden = Mock(side_effect=AssertionError("Use only Stonks search"))
    for name in (
        "SolanaRpcClient",
        "TokenScanner",
        "TokenContext",
        "JupiterClient",
        "RugcheckClient",
        "StonksTokenClient",
        "LaunchEnricher",
        "OnChainEnricher",
    ):
        monkeypatch.setattr(growr, name, forbidden)
    yield get, close
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    ("options", "sort", "page", "size"),
    [
        ([], "marketCap", 1, 30),
        (["--sort", "marketCap", "--page", "2"], "marketCap", 2, 30),
        (["--sort", "volume", "--page-size", "2"], "volume", 1, 2),
        (["--sort", "newest", "--page-size", "100"], "newest", 1, 100),
    ],
)
@pytest.mark.parametrize("query", ["  te  ", MINT, "one, two & three"])
def test_search_sends_q_and_retains_the_returned_page(
    monkeypatch, capsys, stonks_io, options, sort, page, size, query
):
    get, close = stonks_io
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            "--json",
            "--include-raw",
            "search",
            "stonks",
            query,
            *options,
        ],
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    document = validate(json.loads(output.out))
    assert document["request"] == {
        "command": "search",
        "target": None,
        "options": {
            "source": "stonks",
            "mode": "search",
            "query": query.strip(),
            "include_raw": True,
            "sort": sort,
            "page": page,
            "page_size": size,
        },
        "rpc": None,
    }
    assert document["status"] == "success"
    assert document["pagination"] == DATA["pagination"]
    assert document["raw"]["discovery"] == ENVELOPE
    assert get.return_value.json.return_value == ENVELOPE
    assert [row["identity"]["pool"] for row in document["records"]] == [
        "pool-a",
        "pool-b",
        "pool-c",
    ]
    assert [row["identity"]["mint"] for row in document["records"]] == [
        OTHER,
        MINT,
        MINT,
    ]
    for record in document["records"]:
        assert record["kind"] == "pool"
        assert record["facts"]["source"] == "stonks"
        assert record["on_chain"] is None
        assert [item["source"] for item in record["coverage"]] == ["stonks"]
        assert record["social"]["coverage"] == {"stonks": "success"}
    market = document["records"][1]["metrics"]["market"]
    assert market["price_usd"] == {
        "value": 0,
        "source": "stonks",
        "scope": "pool",
    }
    assert market["market_cap_usd"]["value"] == 80
    assert market["stonks_volume_24h_usd"]["value"] == 30
    assert document["records"][1]["social"]["score"] == 80
    assert len(document["coverage"]) == 1
    get.assert_called_once_with(
        "%s/tokens" % settings.STONKS_API_URL,
        params={
            "q": query.strip(),
            "sort": sort,
            "page": page,
            "pageSize": size,
        },
        headers=None,
        timeout=5,
    )
    close.assert_called_once()
    assert output.err == ""


def test_console_search_uses_returned_pagination_and_full_mints(
    monkeypatch, capsys, stonks_io
):
    monkeypatch.setattr("sys.argv", ["growr.py", "search", "stonks", "te"])
    assert growr.main() == 0
    output = capsys.readouterr()
    for value in (
        "Stonks search",
        "Test token",
        MINT,
        OTHER,
        "80/100",
        "0 S",
        "https://project.example",
        "page: 3, pages: 7, page size: 5, total: 33",
    ):
        assert value in output.out
    assert any(
        line.startswith("11  Server candidate")
        for line in output.out.splitlines()
    )
    assert "Jupiter" not in output.out
    assert "On-chain observations" not in output.out
    assert output.err == ""


@pytest.mark.parametrize("json_mode", [False, True])
def test_empty_query_page_keeps_pagination(
    monkeypatch, capsys, stonks_io, json_mode
):
    get, close = stonks_io
    get.return_value.json.return_value["data"]["tokens"] = []
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "search", "stonks", "te"]
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    if json_mode:
        document = validate(json.loads(output.out))
        assert document["status"] == "no_data"
        assert document["records"] == []
        assert document["pagination"] == DATA["pagination"]
        assert document["coverage"][0]["status"] == "no_data"
    else:
        assert "No matching pools on this page." in output.out
    assert output.err == ""
    close.assert_called_once()


@pytest.mark.parametrize(
    "failure", ["transport", "http", "json", "shape", "mint"]
)
def test_failed_search_closes_http_and_returns_safe_error(
    monkeypatch, capsys, stonks_io, failure
):
    get, close = stonks_io
    response = get.return_value
    if failure == "transport":
        get.side_effect = requests.Timeout("private-response-secret")
    elif failure == "http":
        response.ok = False
        response.status_code = 503
    elif failure == "json":
        response.json.side_effect = ValueError("private-response-secret")
    elif failure == "shape":
        response.json.return_value = {"pools": None}
    else:
        response.json.return_value = {
            "pools": [{"mint": "private-response-secret"}]
        }
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "search", "stonks", "te"]
    )
    assert growr.main() == 1
    output = capsys.readouterr()
    document = validate(json.loads(output.out))
    assert document["error"]["code"] == "EXECUTION_FAILED"
    assert document["request"]["options"]["source"] == "stonks"
    assert document["records"] == []
    assert "private-response-secret" not in output.out + output.err
    assert output.err == ""
    close.assert_called_once()


@pytest.mark.parametrize(
    "options",
    [
        [],
        [""],
        ["  "],
        ["te", "--sort", "recent"],
        ["te", "--page", "0"],
        ["te", "--page-size", "-1"],
        ["te", "--page-size", "bad"],
        ["te", "--page-size", "101"],
        ["te", "--on-chain"],
        ["te", "--category", "xstock"],
        ["te", "--interval", "1h"],
    ],
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_bad_stonks_query_arguments_fail_before_clients(
    monkeypatch, capsys, options, json_mode
):
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "search", "stonks", *options]
    )
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    if json_mode:
        assert growr.main() == 2
        output = capsys.readouterr()
        assert (
            validate(json.loads(output.out))["error"]["code"]
            == "INVALID_ARGUMENTS"
        )
        assert output.err == ""
    else:
        with pytest.raises(SystemExit) as error:
            growr.main()
        assert error.value.code == 2
        if not options:
            assert "search stonks te" in capsys.readouterr().err
    http.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [{"sort": "recent"}, {"page": True}, {"page_size": 0}, {"page": "2"}],
)
def test_library_query_rejects_bad_options_before_http(options):
    http = Mock()
    with pytest.raises(ValueError):
        StonksClient(http).search_pools("te", **options)
    http.get_json.assert_not_called()
