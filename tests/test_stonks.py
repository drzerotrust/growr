"""Stonks discovery and CLI integration without live requests."""

import json
from functools import partial
from unittest.mock import Mock

import pytest
import requests

import growr
from growr_cli import settings
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.stonks import StonksClient
from growr_cli.models import ScanReport
from growr_cli.searchers import StonksSearcher
from tests.test_enrichment import MINT, OTHER, launch_report, providers_for


def response(payload):
    return Mock(ok=True, status_code=200, json=Mock(return_value=payload))


def searcher(mode="recent", page=None, page_size=None, category=None):
    finder = StonksSearcher(
        StonksClient(HttpClient(settings.REQUEST_TIMEOUT_SECONDS))
    )
    finder.search = partial(
        finder.search,
        mode,
        page=page or 1,
        page_size=page_size or 30,
        category=category,
    )
    return finder


@pytest.mark.parametrize("pools", [[], [{"mint": MINT, "pending": True}]])
def test_discovery_status_and_envelope(monkeypatch, pools):
    payload = {
        "pools": pools,
        "generatedAt": "source-time",
        "windowMs": 600000,
    }
    get = Mock(return_value=response(payload))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    report = searcher().search()
    assert report.findings.status == ("success" if pools else "no_data")
    assert report.findings.tokens == payload
    assert isinstance(report.findings.timestamp, float)
    assert get.call_args.kwargs["timeout"] > 0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"pools": None},
        {"pools": [None]},
        {"pools": [{}]},
        {"pools": [{"mint": "invalid"}]},
    ],
)
def test_discovery_rejects_invalid_payload(monkeypatch, payload):
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(return_value=response(payload)),
    )
    with pytest.raises(ValueError, match="Stonks returned"):
        searcher().search()


def test_discovery_errors_do_not_expose_credentials(monkeypatch):
    get = Mock(
        side_effect=requests.Timeout("https://stonks.example?api-key=secret")
    )
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    with pytest.raises(ValueError, match="Stonks request failed") as error:
        searcher().search()
    assert "secret" not in str(error.value)


def test_discovery_invalid_json_and_http_failure(monkeypatch):
    resp = response(None)
    resp.json.side_effect = ValueError("secret body")
    get = Mock(return_value=resp)
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    with pytest.raises(ValueError, match="Stonks returned invalid JSON"):
        searcher().search()
    resp.ok = False
    resp.status_code = 503
    with pytest.raises(ValueError, match="Stonks returned HTTP 503"):
        searcher().search()


def cli_dependencies(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["growr.py", *argv])
    monkeypatch.setattr(
        growr,
        "StonksSearcher",
        Mock(return_value=Mock(search=Mock(return_value=launch_report()))),
    )
    client = providers_for([MINT])
    monkeypatch.setattr(
        growr, "JupiterClient", Mock(return_value=client.jupiter)
    )
    monkeypatch.setattr(
        growr, "DexscreenerClient", Mock(return_value=client.dexscreener)
    )
    rpc = Mock()
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    return client, rpc


@pytest.mark.parametrize("provider", ["--stonk", "stonks"])
def test_cli_default_has_no_rpc_and_emits_tables(
    monkeypatch, capsys, provider
):
    _, rpc = cli_dependencies(
        monkeypatch, ["list", provider, "--stonk-search", "recent"]
    )
    assert growr.main() == 0
    rpc.assert_not_called()
    captured = capsys.readouterr()
    assert "Provider-reported risk" in captured.out
    assert "\x1b" not in captured.out
    assert captured.err == ""
    assert "\x1b" not in captured.err


def test_cli_on_chain_is_opt_in_and_skips_duplicate_market_requests(
    monkeypatch, capsys
):
    client, rpc = cli_dependencies(
        monkeypatch, ["--json", "list", "--stonk", "--on-chain"]
    )
    scan = Mock(return_value=ScanReport("token", MINT, "test", "now"))
    monkeypatch.setattr(
        growr, "TokenScanner", Mock(return_value=Mock(scan=scan))
    )
    assert growr.main() == 0
    scan.assert_called_once_with(
        MINT,
        include_jupiter=False,
        include_rugcheck=False,
        include_market_context=False,
    )
    rpc.return_value.close.assert_called_once()
    client.get_jupiter_tokens.assert_called_once_with([MINT])
    data = json.loads(capsys.readouterr().out)
    assert data["records"][0]["on_chain"]["kind"] == "token"


def test_cli_discovery_failure_emits_structured_error(monkeypatch, capsys):
    cli_dependencies(monkeypatch, ["--json", "list", "--stonk"])
    growr.StonksSearcher.return_value.search.side_effect = ValueError(
        "Stonks returned HTTP 503"
    )
    assert growr.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["code"] == "EXECUTION_FAILED"
    assert captured.err == ""


def test_token_account_dispatch(monkeypatch, capsys):
    cli_dependencies(monkeypatch, ["--json", "token-account", MINT])
    scanner = Mock(
        return_value=Mock(
            scan=Mock(
                return_value=ScanReport("token_account", MINT, "test", "now")
            )
        )
    )
    monkeypatch.setattr(growr, "TokenAccountScanner", scanner)
    assert growr.main() == 0
    scanner.return_value.scan.assert_called_once_with(MINT)
    assert (
        json.loads(capsys.readouterr().out)["records"][0]["kind"]
        == "token_account"
    )


@pytest.mark.parametrize("mode", ["marketCap", "volume"])
@pytest.mark.parametrize(("page", "size"), [(None, None), (2, 7)])
def test_platform_query_parameters_and_envelope(monkeypatch, mode, page, size):
    payload = {
        "pools": [{"mint": MINT}],
        "featured": {"mint": OTHER},
        "pagination": {
            "page": page or 1,
            "pageSize": size or 30,
            "total": 99,
            "totalPages": 4,
        },
    }
    get = Mock(return_value=response(payload))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    finder = searcher(mode, page, size)
    result = finder.search()
    assert result.search_type == f"stonk-{mode}"
    assert result.findings.tokens == payload
    get.assert_called_once()
    assert get.call_args.args[0] == f"{settings.STONKS_API_URL}/platform-pools"
    assert get.call_args.kwargs["params"] == {
        "sort": mode,
        "page": page or 1,
        "pageSize": size or 30,
    }


def test_recent_query_has_no_pagination(monkeypatch):
    get = Mock(return_value=response({"pools": []}))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    searcher().search()
    assert get.call_args.args[0].endswith("/recent-launches")
    assert get.call_args.kwargs["params"] is None


@pytest.mark.parametrize("mode", ["marketCap", "volume"])
@pytest.mark.parametrize(
    "category",
    ["xstock", "prestock", "custom", "collectibles", "currencies", "leverage"],
)
def test_category_cli_filters_server_query_and_preserves_results(
    monkeypatch, capsys, mode, category
):
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            "--json",
            "--include-raw",
            "list",
            "--stonk",
            "--stonk-search",
            mode,
            "--category",
            category,
            "--page",
            "2",
            "--page-size",
            "5",
        ],
    )
    payload = {
        "pools": [{"mint": MINT}],
        "featured": {"mint": OTHER},
        "pagination": {"page": 2, "pageSize": 5, "total": 6},
    }
    original = json.loads(json.dumps(payload))
    get = Mock(return_value=response(payload))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    providers = providers_for([MINT])
    monkeypatch.setattr(
        growr, "JupiterClient", Mock(return_value=providers.jupiter)
    )
    monkeypatch.setattr(
        growr, "DexscreenerClient", Mock(return_value=providers.dexscreener)
    )
    rpc = Mock()
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)

    assert growr.main() == 0

    get.assert_called_once()
    assert get.call_args.args[0].endswith("/platform-pools")
    assert get.call_args.kwargs["params"] == {
        "sort": mode,
        "page": 2,
        "pageSize": 5,
        "category": category,
    }
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["request"]["options"]["mode"] == mode
    assert report["records"][0]["raw"]["jupiter"]["id"] == MINT
    assert report["raw"]["discovery"] == original
    providers.get_jupiter_tokens.assert_called_once_with([MINT])
    rpc.assert_not_called()
    assert output.err == ""


@pytest.mark.parametrize(
    "arguments",
    [
        ["--stonk", "--category", "xstock"],
        ["--stonk", "--stonk-search", "recent", "--category", "prestock"],
        ["--boosted", "--category", "custom"],
        ["--community-takeovers", "--category", "collectibles"],
        ["--stonk", "--stonk-search", "volume", "--category", "invalid"],
        ["--stonk", "--stonk-search", "marketCap", "--category"],
    ],
)
def test_invalid_category_options_fail_before_requests(
    monkeypatch, capsys, arguments
):
    monkeypatch.setattr("sys.argv", ["growr.py", "list", *arguments])
    get = Mock()
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )

    with pytest.raises(SystemExit) as error:
        growr.main()

    assert error.value.code == 2
    assert "--category" in capsys.readouterr().err
    get.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--stonk", "--stonk-search", "bad"],
        ["--stonk", "--page", "1"],
        ["--stonk", "--stonk-search", "recent", "--page-size", "30"],
        ["--boosted", "--page", "2"],
        ["--community-takeovers", "--page-size", "10"],
        ["--stonk-search", "volume"],
        ["--stonk", "--stonk-search", "volume", "--page", "0"],
        ["--stonk", "--stonk-search", "marketCap", "--page", "-1"],
        ["--stonk", "--stonk-search", "volume", "--page-size", "0"],
        ["--stonk", "--stonk-search", "volume", "--page-size", "1.5"],
        ["--stonk", "--stonk-search", "marketCap", "--page", "abc"],
    ],
)
def test_invalid_pagination_or_search_fails_before_requests(
    monkeypatch, arguments
):
    monkeypatch.setattr("sys.argv", ["growr.py", "list", *arguments])
    get = Mock()
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    with pytest.raises(SystemExit) as error:
        growr.main()
    assert error.value.code == 2
    get.assert_not_called()


@pytest.mark.parametrize("mode", ["marketCap", "volume"])
@pytest.mark.parametrize("as_json", [False, True])
def test_platform_cli_enriches_only_page_preserves_order_and_ranking(
    monkeypatch, capsys, mode, as_json
):
    flags = ["--json", "--include-raw"] if as_json else []
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            *flags,
            "list",
            "--stonk",
            "--stonk-search",
            mode,
            "--page",
            "2",
            "--page-size",
            "2",
        ],
    )
    # Returned pagination can differ from the requested size: use the
    # response for numbering.
    payload = {
        "pools": [
            {
                "mint": MINT,
                "symbol": "FIRST",
                "marketCapUsd": 80,
                "volume24hUsd": 70,
            },
            {
                "mint": OTHER,
                "symbol": "SECOND",
                "marketCapUsd": 60,
                "volume24hUsd": 50,
            },
        ],
        "featured": {"mint": "11111111111111111111111111111111"},
        "pagination": {"page": 2, "pageSize": 5, "total": 7, "totalPages": 2},
        "source": "api-source",
    }
    original = json.loads(json.dumps(payload))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(return_value=response(payload)),
    )
    client = providers_for([MINT, OTHER], {"mcap": 999})
    monkeypatch.setattr(
        growr, "JupiterClient", Mock(return_value=client.jupiter)
    )
    monkeypatch.setattr(
        growr, "DexscreenerClient", Mock(return_value=client.dexscreener)
    )
    rpc = Mock()
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    assert growr.main() == 0
    rpc.assert_not_called()
    client.get_jupiter_tokens.assert_called_once_with([MINT, OTHER])
    output = capsys.readouterr().out
    if as_json:
        result = json.loads(output)
        assert result["request"]["options"]["mode"] == mode
        assert [row["identity"]["mint"] for row in result["records"]] == [
            MINT,
            OTHER,
        ]
        assert result["raw"]["discovery"] == original
        assert result["pagination"] == original["pagination"]
    else:
        assert output.index("6. FIRST") < output.index("7. SECOND")
        assert "page: 2, pages: 2, page size: 5, total: 7" in output
        assert (
            "Stonks Mcap $" if mode == "marketCap" else "Stonks 24h vol $"
        ) in output
        assert ("80 S" if mode == "marketCap" else "70 S") in output
        assert "999 J" in output and "dexscreener=no_data" in output


@pytest.mark.parametrize("mode", ["marketCap", "volume"])
def test_platform_empty_page_and_error(monkeypatch, capsys, mode):
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "list", "--stonk", "--stonk-search", mode]
    )
    get = Mock(
        return_value=response(
            {
                "pools": [],
                "pagination": {
                    "page": 99,
                    "pageSize": 30,
                    "total": 7,
                    "totalPages": 1,
                },
            }
        )
    )
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    providers = Mock()
    monkeypatch.setattr(
        growr, "JupiterClient", Mock(return_value=providers.jupiter)
    )
    monkeypatch.setattr(
        growr, "DexscreenerClient", Mock(return_value=providers.dexscreener)
    )
    assert growr.main() == 0
    assert not providers.mock_calls
    assert "No pools on this page." in capsys.readouterr().out
    get.return_value = Mock(ok=False, status_code=400)
    assert growr.main() == 1
    assert "HTTP 400" in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["marketCap", "volume"])
def test_platform_optional_rpc(monkeypatch, capsys, mode):
    client, rpc = cli_dependencies(
        monkeypatch,
        ["--json", "list", "--stonk", "--stonk-search", mode, "--on-chain"],
    )
    growr.StonksSearcher.return_value.search.return_value.search_type = (
        f"stonk-{mode}"
    )
    scanner = Mock(
        return_value=Mock(
            scan=Mock(return_value=ScanReport("token", MINT, "test", "now"))
        )
    )
    monkeypatch.setattr(growr, "TokenScanner", scanner)
    assert growr.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["records"][0]["on_chain"]["kind"] == "token"
    rpc.assert_called_once()
