"""Social evidence, provider isolation, and listing presentation."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from growr_cli.analysis.social import social_presence
from growr_cli.enrichment.social import attach_social
from growr_cli.integrations.dexscreener import social_links as dex_links
from growr_cli.integrations.stonks import social_links as stonks_links
from growr_cli.models import EnrichmentResult
from growr_cli.output import renderer_for
from growr_cli.searchers import DexscreenerTokenSearcher
from tests.test_enrichment import (
    MINT,
    OTHER,
    enricher,
    launch_report,
    providers_for,
)


def evidence(website=None, twitter=None, telegram=None):
    return stonks_links(
        {
            "website": website,
            "twitter": twitter,
            "telegram": telegram,
        }
    )


@pytest.mark.parametrize(
    ("website", "twitter", "telegram", "score"),
    [
        (None, None, None, 0),
        ("https://project.test", None, None, 40),
        (None, "https://x.com/project", None, 40),
        (None, "https://x.com/project", "https://t.me/project", 60),
        ("https://project.test", "https://x.com/project", None, 80),
        (
            "https://project.test",
            "https://x.com/project",
            "https://t.me/project",
            100,
        ),
    ],
)
def test_presence_formula(website, twitter, telegram, score):
    result = social_presence(evidence(website, twitter, telegram), {})
    assert result["score"] == score
    assert result["max_score"] == 100


@pytest.mark.parametrize(
    "url",
    [
        None,
        {},
        "",
        "@project",
        "javascript:alert(1)",
        "https://user:password@example.com",
        "https://project.test/\x1b[31m",
        "https://project.test:broken",
        "https://[broken",
        "https://bad host/a",
        "https://dexscreener.com/solana/mint",
        "https://www.stonkfun.xyz/launch",
    ],
)
def test_invalid_or_provider_links_do_not_score(url):
    assert social_presence(evidence(url, url, url), {})["score"] == 0


def test_deduplicate_links_platforms_and_merge_sources():
    candidates = evidence(
        "https://PROJECT.test:443/#section", "http://twitter.com/Project/"
    )
    candidates += dex_links(
        {
            "links": [
                {"label": "Website", "url": "https://project.test"},
                {"type": "twitter", "url": "https://x.com/project"},
                {"type": "twitter", "url": "https://x.com/other"},
            ]
        },
        discovery=True,
    )
    result = social_presence(candidates, {"dexscreener": "success"})
    assert result["score"] == 80
    assert result["platforms"] == ["twitter"]
    assert len(result["links"]) == 3
    assert result["links"][0]["sources"] == ["stonks", "dexscreener"]
    assert result["links"][1]["sources"] == ["stonks", "dexscreener"]


def test_social_url_in_website_field_is_not_counted_twice():
    result = social_presence(evidence("https://x.com/project"), {})
    assert result["score"] == 40
    assert result["has_website"] is False


def test_malformed_provider_fields_and_bare_handles_are_ignored():
    candidates = dex_links(
        {
            "info": {
                "websites": [None, {}, {"url": "https://project.test"}],
                "socials": [{"platform": "twitter", "handle": "project"}],
            }
        }
    )
    assert social_presence(candidates, {})["score"] == 40
    assert dex_links({"info": "wrong"}) == []
    assert dex_links({"links": {}}, discovery=True) == []


def test_stonks_uses_all_matching_pairs_without_extra_requests():
    report = launch_report()
    report.findings.tokens["pools"][0]["website"] = "https://project.test"
    client = providers_for([MINT])
    pairs = [
        {
            "chainId": "solana",
            "baseToken": {"address": MINT},
            "pairAddress": "original",
        },
        {
            "chainId": "solana",
            "baseToken": {"address": MINT},
            "pairAddress": "other",
            "info": {"socials": [{"url": "https://x.com/project"}]},
        },
        {
            "chainId": "solana",
            "baseToken": {"address": OTHER},
            "info": {"socials": [{"url": "https://t.me/wrong"}]},
        },
        {
            "chainId": "ethereum",
            "baseToken": {"address": MINT},
            "info": {"socials": [{"url": "https://t.me/wrong"}]},
        },
    ]
    client.dexscreener.get_tokens.return_value[MINT] = EnrichmentResult(
        "success", "now", pairs
    )
    enricher(client).enrich(report)
    analytics = report.findings.tokens["pools"][0]["analytics"]
    assert analytics["social"]["score"] == 80
    assert analytics["social"]["platforms"] == ["twitter"]
    assert (
        analytics["dexscreener"]["selected_pair"]["pairAddress"] == "original"
    )
    client.jupiter.get_tokens.assert_called_once_with([MINT])
    client.dexscreener.get_tokens.assert_called_once_with([MINT])


def test_provider_failure_keeps_stonks_evidence_and_visible_coverage():
    report = launch_report()
    report.findings.tokens["pools"][0]["website"] = "https://project.test"
    client = providers_for([MINT])
    client.dexscreener.get_tokens.return_value[MINT] = EnrichmentResult(
        "failed", "now", None, "HTTP 503"
    )
    enricher(client).enrich(report)
    social = report.findings.tokens["pools"][0]["analytics"]["social"]
    assert social["score"] == 40
    assert social["coverage"]["dexscreener"] == "failed"


def test_discovery_scores_only_solana_and_preserves_raw_records(capsys):
    tokens = [
        {
            "chainId": chain,
            "tokenAddress": f"mint-{chain}",
            "url": "https://dexscreener.com/chart",
            "analytics": {"existing": True},
            "links": [
                {"label": "Website", "url": "https://project.test"},
                {"type": "twitter", "url": "https://x.com/project"},
                {"type": "telegram", "url": "https://t.me/project"},
            ],
        }
        for chain in ("solana", "ethereum")
    ]
    original = deepcopy(tokens)
    client = Mock()
    client.discover.return_value = tokens
    report = DexscreenerTokenSearcher(client).search(boosted=True)
    assert tokens == original
    assert report.raw == original
    assert [row["chainId"] for row in report.findings.tokens] == [
        "solana",
    ]
    for token in report.findings.tokens:
        assert token["analytics"]["existing"] is True
        assert token["analytics"]["social"]["score"] == 100
    client.discover.assert_called_once_with("boosted")
    renderer_for(report, False).render(report)
    output = capsys.readouterr().out
    assert "mint-ethereum" not in output
    assert "100/100" in output
    for url in (
        "https://project.test",
        "https://x.com/project",
        "https://t.me/project",
    ):
        assert url in output
    assert "[dexscreener]" in output


def test_stonks_console_sanitizes_identity_and_keeps_links(capsys):
    report = launch_report()
    token = report.findings.tokens["pools"][0]
    token["symbol"] = "\x1b[31mTOKEN"
    token["website"] = "https://project.test"
    enricher(providers_for([MINT])).enrich(report)
    renderer_for(report, False).render(report)
    output = capsys.readouterr().out
    assert "Social presence" in output
    assert "40/100" in output
    assert "https://project.test [stonks]" in output
    assert "\x1b" not in output


def test_attach_social_preserves_existing_analytics():
    record = {"analytics": {"metric": 1}, "name": "Token"}
    result = attach_social(record, evidence(), {})
    assert result["analytics"]["metric"] == 1
    assert "social" not in record["analytics"]
