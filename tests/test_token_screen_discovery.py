"""Exercise screening against real public discovery serialization."""

import json
import subprocess
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest

import growr
from growr_cli.enrichment.launches import LaunchEnricher
from growr_cli.models import EnrichmentResult
from growr_cli.playbooks import token_screen
from growr_cli.playbooks.screen_inputs import saved_evidence
from growr_cli.playbooks.screen_observations import candidates_from_evidence
from growr_cli.playbooks.screening import evaluate, rank_key
from growr_cli.searchers.jupiter import JupiterTokenSearcher
from growr_cli.searchers.stonks import StonksSearcher
from tests.test_machine import output_for
from tests.test_token_screen import (
    MINT,
    NOW,
    OTHER_MINT,
    address,
    children,
    criteria,
    discovery,
    evaluate_document,
    jupiter_token,
    ranking,
    rpc_document,
    rule,
    write_json,
)


def discovery_for(command, mint=MINT):
    parser = growr.build_parser()
    args = parser.parse_args(command)
    growr._validate_search_arguments(parser, args)
    if args.provider == "jupiter":
        client = Mock(
            discover=Mock(
                return_value=[
                    jupiter_token(mint, liquidity=100, updatedAt=None)
                ]
            )
        )
        mode = "search" if args.scan_type == "search" else args.jupiter_search
        report = JupiterTokenSearcher(client).search(mode)
    else:
        report = stonks_report(args, mint)
    return output_for(report, *command)


def stonks_report(args, mint):
    envelope = {
        "data": {
            "tokens": [
                {
                    "mint": mint,
                    "pool": address(15),
                    "market": {"marketCapUsd": 500, "volume24hUsd": 50},
                    "quote": {"category": "xstock"},
                }
            ],
            "pagination": {"page": args.page, "pageSize": args.page_size},
        }
    }
    client = Mock()
    client.get_pools.return_value = envelope
    client.search_pools.return_value = envelope
    searcher = StonksSearcher(client)
    if args.scan_type == "search":
        return searcher.search_query(args.query)
    report = searcher.search(args.stonk_search)
    jupiter = Mock(
        get_tokens=Mock(
            return_value={
                mint: EnrichmentResult(
                    "success", NOW.isoformat(), jupiter_token(mint)
                )
            }
        )
    )
    # Missing Jupiter cap must preserve the Stonkfun pool fallback.
    LaunchEnricher(jupiter).enrich(report)
    return report


@pytest.mark.parametrize(
    "flags",
    [
        ["--provider", "jupiter"],
        ["--provider", "jupiter", "--feed", "toptraded"],
        ["--provider", "jupiter", "--feed", "toptrending", "--interval", "1h"],
        ["--provider", "jupiter", "--feed", "toporganicscore"],
        ["--provider", "jupiter", "--query", "JUP"],
        ["--provider", "stonks"],
        ["--provider", "stonks", "--feed", "marketCap"],
        ["--provider", "stonks", "--feed", "volume", "--category", "xstock"],
        ["--provider", "stonks", "--query", "te", "--sort", "volume"],
    ],
)
def test_provider_modes_match_actual_cli_contract(
    monkeypatch, tmp_path, capsys, flags
):
    def run(argv, **kwargs):
        command = argv[9:]
        document = discovery_for(command)
        return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")

    process = Mock(side_effect=run)
    monkeypatch.setattr("growr_cli.playbooks.runner.subprocess.run", process)
    field = "liquidity_usd" if flags[1] == "jupiter" else "market_cap_usd"
    config = write_json(tmp_path, "criteria.json", criteria(rule(field, 1)))
    assert token_screen.main(["--criteria", config, *flags, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["matched"] == 1
    assert process.call_count == 1
    condition = report["matches"][0]["requirements"][0]
    assert condition["expected"] == "1"
    if flags[1] == "stonks":
        assert condition["evidence"][0]["scope"] == "pool"
    assert report["scope"]["limits"]["scan_limit"] == 5
    assert report["budget"]["reserved_upper_bounds"]["rpc"] == 0


def test_pages_stop_before_shared_http_budget(monkeypatch, tmp_path, capsys):
    def run(argv, **kwargs):
        document = discovery_for(argv[9:])
        return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")

    process = Mock(side_effect=run)
    monkeypatch.setattr("growr_cli.playbooks.runner.subprocess.run", process)
    config = write_json(tmp_path, "criteria.json", criteria())
    assert (
        token_screen.main(
            [
                "--criteria",
                config,
                "--provider",
                "stonks",
                "--pages",
                "10",
                "--max-http-calls",
                "3",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert process.call_count == 1
    assert report["counts"]["evaluated"] == 1
    assert report["gaps"] == ["http_budget_exhausted"]
    assert report["budget"]["reserved_upper_bounds"]["http"] == 2


def test_live_report_replays_rpc_evidence_and_receipts(
    monkeypatch, tmp_path, capsys
):
    process = children(monkeypatch, {("token", MINT): rpc_document()})
    config = write_json(tmp_path, "criteria.json", criteria(verify=True))
    assert (
        token_screen.main(["--criteria", config, "--mints", MINT, "--json"])
        == 0
    )
    original = json.loads(capsys.readouterr().out)
    saved = write_json(tmp_path, "screen.json", original)
    assert (
        token_screen.main(["--criteria", config, "--input", saved, "--json"])
        == 0
    )
    replay = json.loads(capsys.readouterr().out)
    assert process.call_count == 1
    assert replay["counts"] == original["counts"]
    assert replay["evidence"] == original["evidence"]
    assert replay["scans"] == []
    assert replay["scope"]["source_scans"] == original["scans"]


def test_descending_ranking_preserves_more_than_28_digits():
    evidence = []
    for mint, amount in (
        (MINT, "900719925474099300000000000001"),
        (OTHER_MINT, "900719925474099300000000000002"),
    ):
        rows, _, _ = saved_evidence(discovery([mint], liquidity=amount))
        evidence.extend(rows)
    values = candidates_from_evidence(evidence, [MINT, OTHER_MINT], NOW)
    rows = sorted(
        [evaluate(row, criteria(ranking=[ranking()]), NOW) for row in values],
        key=rank_key,
    )
    assert [row["mint"] for row in rows] == [OTHER_MINT, MINT]


def test_pool_age_is_creation_age_and_missing_is_unknown():
    first = (NOW - timedelta(hours=2)).isoformat()
    result = evaluate_document(
        discovery(firstPool={"createdAt": first}),
        criteria(rule("first_pool_age_hours", 2, "eq")),
    )
    assert result["decision"] == "pass"
    assert (
        evaluate_document(
            discovery(), criteria(rule("first_pool_age_hours", 2))
        )["decision"]
        == "unknown"
    )


@pytest.mark.parametrize("supply", [None, "0"])
def test_missing_or_zero_supply_cannot_establish_concentration(supply):
    document = rpc_document(supply=supply)
    document["records"][0]["facts"]["holders"]["top_twenty_percent"] = 0
    assert (
        evaluate_document(
            document, criteria(rule("top_20_accounts_pct", 20, "lte"))
        )["decision"]
        == "unknown"
    )


def test_saved_rpc_requires_explicit_listing_verification():
    document = discovery()
    document["records"][0]["on_chain"] = rpc_document()["records"][0]
    with pytest.raises(ValueError):
        saved_evidence(document)
    allowed = deepcopy(document)
    allowed["request"]["command"] = "list"
    allowed["request"]["options"]["on_chain"] = True
    evidence, _, _ = saved_evidence(allowed)
    assert len(evidence) == 2
