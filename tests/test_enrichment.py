"""Tests for enrichment, provenance, and optional verification."""

import json
from copy import deepcopy
from threading import Barrier, Lock
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

from growr_cli.enrichment import (
    LaunchEnricher,
    activity_metrics,
    normalize,
)
from growr_cli.models import (
    EnrichmentResult,
    ScanReport,
    SearchReport,
    TokenSearches,
)
from growr_cli.renderers.stonkfun import StonkfunConsoleRenderer

MINT = "So11111111111111111111111111111111111111112"
OTHER = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def launch_report(launches=None):
    if launches is None:
        launches = [
            {
                "mint": MINT,
                "pool": "original",
                "symbol": "SAME",
                "marketCapUsd": 10,
                "transferTaxBps": 100,
            }
        ]
    return SearchReport(
        "stonk-recent",
        TokenSearches(
            {
                "pools": launches,
                "network": "mainnet-beta",
                "generatedAt": "source-time",
                "windowMs": 600000,
            },
            100.0,
            "stonk",
            "success" if launches else "no_data",
        ),
    )


def providers_for(mints, jupiter=None):
    client = Mock()
    client.get_jupiter_tokens.return_value = {
        mint: EnrichmentResult(
            "success",
            "jupiter-time",
            jupiter or {"id": mint, "holderCount": 4},
        )
        for mint in mints
    }
    client.jupiter.get_tokens = client.get_jupiter_tokens
    return client


def enricher(client, scan=None):
    return LaunchEnricher(client.jupiter, scan)


def test_jupiter_preserves_discovery_and_unknowns():
    report = launch_report()
    original = deepcopy(report.to_dict())
    result = enricher(providers_for([MINT])).enrich(report).to_dict()
    pool = result["findings"]["tokens"]["pools"][0]
    analytics = pool.pop("analytics")
    assert result == original
    assert analytics["jupiter"]["fetched_at"] == "jupiter-time"
    assert analytics["on_chain"] is None
    assert (
        analytics["metrics"]["market"]["token_liquidity_usd"]["value"] is None
    )
    assert analytics["metrics"]["risk"]["holderCount"] == {
        "value": 4,
        "source": "jupiter",
        "scope": "token",
    }


def test_duplicate_mints_are_requested_once_but_launch_order_is_kept():
    launches = [
        {"mint": mint, "pool": str(index)}
        for index, mint in enumerate([MINT, OTHER, MINT])
    ]
    client = providers_for([MINT, OTHER])
    scan = Mock(return_value=ScanReport("token", MINT, "test", "now"))
    result = enricher(client, scan).enrich(launch_report(launches))
    client.get_jupiter_tokens.assert_called_once_with([MINT, OTHER])
    assert scan.call_count == 2
    assert [pool["pool"] for pool in result.findings.tokens["pools"]] == [
        "0",
        "1",
        "2",
    ]


def test_rpc_failure_is_local_and_redacted():
    def scan(mint):
        if mint == MINT:
            raise RuntimeError("https://rpc.example?api-key=secret")
        return ScanReport(
            "token",
            mint,
            "test RPC",
            "now",
            summary={"mint": {"supply": "100"}},
        )

    result = (
        enricher(providers_for([MINT, OTHER]), scan)
        .enrich(launch_report([{"mint": MINT}, {"mint": OTHER}]))
        .to_dict()
    )
    first, second = result["findings"]["tokens"]["pools"]
    assert first["analytics"]["on_chain"]["status"] == "failed"
    assert first["analytics"]["jupiter"]["status"] == "success"
    assert (
        second["analytics"]["on_chain"]["data"]["summary"]["mint"]["supply"]
        == "100"
    )
    assert "secret" not in json.dumps(result)


def test_empty_discovery_does_not_call_any_provider():
    client, scan = Mock(), Mock()
    enricher(client, scan).enrich(launch_report([]))
    assert not client.mock_calls
    scan.assert_not_called()


@pytest.mark.parametrize(
    ("buy", "sell", "net", "share"),
    [(10, 5, 5, 2 / 3), (0, 0, 0, None), (0, 10, -10, 0)],
)
def test_activity_calculations(buy, sell, net, share):
    stats = activity_metrics(
        {"stats5m": {"buyVolume": buy, "sellVolume": sell}}
    )["5m"]["jupiter"]
    assert stats["net_buy_volume_usd"]["value"] == net
    assert stats["buy_volume_share"]["value"] == share


@pytest.mark.parametrize(
    "bad", [None, "invalid", float("nan"), float("inf"), True, -1]
)
def test_incomplete_or_invalid_activity_has_no_derived_ratio(bad):
    stats = activity_metrics(
        {"stats5m": {"buyVolume": 10, "sellVolume": bad}},
    )
    assert "buy_volume_share" not in stats["5m"]["jupiter"]


def test_fallback_and_liquidity_scope_keep_zero_and_sources():
    result = normalize(
        {"marketCapUsd": 5, "priceUsd": 0.002},
        {"mcap": 0, "liquidity": 100},
    )
    market = result["market"]
    assert market["market_cap_usd"]["value"] == 0
    assert market["market_cap_usd"]["source"] == "jupiter"
    assert market["price_usd"]["source"] == "stonks"
    assert market["token_liquidity_usd"] == {
        "value": 100.0,
        "source": "jupiter",
        "scope": "token",
    }
    assert "pool_liquidity_usd" not in market
    assert (
        normalize({"marketCapUsd": 5}, {})["market"]["market_cap_usd"][
            "source"
        ]
        == "stonks"
    )


def test_table_sanitizes_external_text_and_preserves_json(capsys):
    launches = [
        {
            "mint": MINT,
            "symbol": "SAME\x1b[31m\n\r\u202e",
            "transferTaxBps": 100,
        },
        {"mint": OTHER, "symbol": "SAME"},
    ]
    report = enricher(
        providers_for(
            [MINT, OTHER],
            {
                "id": MINT,
                "organicScore": 0,
                "holderCount": 0,
                "audit": {"mintAuthorityDisabled": False},
            },
        )
    ).enrich(launch_report(launches))
    renderer = StonkfunConsoleRenderer(False)
    renderer.render(report)
    text = capsys.readouterr().out
    assert "\x1b" not in text and "\u202e" not in text and "\r" not in text
    assert "So11…1112" in text and "EPjF…Dt1v" in text
    assert (
        "enabled J" in text
        and "0 J" in text
        and "1% S" in text
        and "—" in text
    )
    assert "jupiter=success" in text


def test_rpc_and_provider_observations_are_displayed_separately(capsys):
    scan = Mock(
        return_value=ScanReport(
            "token",
            MINT,
            "test",
            "now",
            summary={
                "mint": {"mint_authority": None, "freeze_authority": None},
                "holders": {"top_twenty_percent": 70},
            },
        )
    )
    client = providers_for(
        [MINT],
        {"audit": {"mintAuthorityDisabled": False, "topHoldersPercentage": 5}},
    )
    report = enricher(client, scan).enrich(launch_report())
    StonkfunConsoleRenderer(False).render(report)
    text = capsys.readouterr().out
    assert "enabled J" in text and "disabled R" in text
    assert "5% J" in text and "70% R" in text
    assert "Token-2022 extensions are not decoded" in text


def test_rpc_scans_use_at_most_two_workers():
    barrier, lock = Barrier(2, timeout=3), Lock()
    active = 0
    maximum = 0

    def scan(mint):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait()
        with lock:
            active -= 1
        return ScanReport("token", mint, "test", "now")

    mints = [str(Pubkey.from_bytes(bytes([i]) * 32)) for i in range(4)]
    report = enricher(providers_for(mints), scan).enrich(
        launch_report([{"mint": mint} for mint in mints])
    )
    assert maximum == 2
    assert all(
        pool["analytics"]["on_chain"]["status"] == "success"
        for pool in report.findings.tokens["pools"]
    )
