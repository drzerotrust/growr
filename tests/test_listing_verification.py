"""Provider selection and shared RPC coverage without network calls."""

import json
from unittest.mock import Mock

import pytest

import growr
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.models import ScanReport
from growr_cli.searchers import DexscreenerTokenSearcher
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import STAMP, validate


@pytest.mark.parametrize(
    ("arguments", "stonks", "boosted"),
    [
        (["stonks"], True, False),
        (["dexscreener"], False, True),
        (["dexcreener"], False, True),
        (["dexscreener", "--community-takeovers"], False, False),
        (["--boosted"], False, True),
    ],
)
def test_provider_selection(arguments, stonks, boosted):
    parser = growr.build_parser()
    args = parser.parse_args(["list", *arguments, "--on-chain"])
    growr._validate_search_arguments(parser, args)
    assert args.stonk == stonks
    assert args.boosted == boosted
    assert args.on_chain


@pytest.mark.parametrize(
    "arguments",
    [
        ["stonks", "--boosted"],
        ["stonks", "--community-takeovers"],
        ["dexscreener", "--stonk"],
        ["dexscreener", "--page", "2"],
        ["dexscreener", "--category", "xstock"],
        ["dexscreener", "--stonk-search", "volume"],
    ],
)
def test_conflicting_provider_options_fail_before_network(arguments):
    parser = growr.build_parser()
    args = parser.parse_args(["list", *arguments])
    with pytest.raises(SystemExit) as error:
        growr._validate_search_arguments(parser, args)
    assert error.value.code == 2


@pytest.mark.parametrize("json_mode", [False, True])
def test_dex_verification_filters_chains_and_closes_rpc(
    monkeypatch, capsys, json_mode
):
    tokens = [
        {"chainId": "solana", "tokenAddress": MINT},
        {"chainId": "ethereum", "tokenAddress": MINT},
        {"chainId": "solana", "tokenAddress": MINT},
        {"chainId": "solana", "tokenAddress": "invalid"},
        {"chainId": "solana"},
        {"chainId": "solana", "tokenAddress": OTHER},
        {"tokenAddress": MINT},
    ]
    get = Mock(return_value=Mock(ok=True, json=Mock(return_value=tokens)))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get", get
    )
    clients = []

    def rpc_client(*args):
        client = Mock()
        clients.append(client)
        return client

    def scan(mint, **options):
        assert options == {
            "include_jupiter": False,
            "include_rugcheck": False,
            "include_market_context": False,
        }
        if mint == OTHER:
            raise ValueError("private endpoint secret")
        return ScanReport("token", mint, "test RPC", STAMP)

    scanner = Mock(return_value=Mock(scan=Mock(side_effect=scan)))
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc_client)
    monkeypatch.setattr(growr, "TokenScanner", scanner)
    flags = ["--json", "--include-raw"] if json_mode else []
    monkeypatch.setattr(
        "sys.argv",
        ["growr.py", *flags, "list", "dexscreener", "--on-chain"],
    )
    assert growr.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "secret" not in captured.out + captured.err
    assert scanner.call_count == len(clients) == 2
    for client in clients:
        client.close.assert_called_once()
    get.assert_called_once()
    if not json_mode:
        assert "On-chain observations" in captured.out
        assert "ethereum" not in captured.out
        assert "failed" in captured.out
        return

    report = json.loads(captured.out)
    validate(report)
    assert report["status"] == "partial"
    assert report["request"]["options"]["on_chain"] is True
    assert report["raw"]["discovery"] == tokens
    records = report["records"]
    assert len(records) == 5
    assert all(record["identity"]["chain"] == "solana" for record in records)
    statuses = [
        next(
            item["status"]
            for item in record["coverage"]
            if item["operation"] == "token_scan"
        )
        for record in records
    ]
    assert statuses == [
        "success",
        "success",
        "failed",
        "failed",
        "failed",
    ]
    assert records[0]["on_chain"]["kind"] == "token"
    assert records[0]["on_chain"] == records[1]["on_chain"]
    assert records[2]["on_chain"] is None


@pytest.mark.parametrize("tokens", [[], [{"chainId": "ethereum"}]])
def test_no_eligible_mints_never_invoke_rpc(tokens):
    discovery = Mock(discover=Mock(return_value=tokens))
    report = DexscreenerTokenSearcher(discovery).search(boosted=True)
    scan = Mock()
    assert OnChainEnricher(scan).enrich(report) is report
    scan.assert_not_called()
