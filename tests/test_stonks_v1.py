"""Public v1 payloads, safe failures and pagination boundaries."""

import json
from contextlib import closing
from copy import deepcopy
from unittest.mock import Mock

import pytest

import growr
from growr_cli import settings
from growr_cli.integrations.http import HttpClient, retry_delay
from growr_cli.integrations.stonks import StonksClient
from growr_cli.integrations.stonks_token import StonksTokenClient
from growr_cli.searchers.stonks import StonksSearcher
from tests.test_enrichment import MINT
from tests.test_machine import validate


@pytest.mark.parametrize("status", [404, 429, 503])
def test_public_errors_keep_codes_and_hide_messages(monkeypatch, status):
    code = {404: "not_found", 429: "rate_limited", 503: "internal"}[status]
    payload = {"error": {"code": code, "message": "private-server-message"}}
    get = Mock(
        return_value=Mock(
            ok=False,
            status_code=status,
            headers={"Retry-After": "17"},
            json=Mock(return_value=payload),
        )
    )
    monkeypatch.setattr("requests.Session.get", get)
    with closing(HttpClient(5)) as http:
        result = StonksTokenClient(http).get_market(MINT)
    assert result.status == ("no_data" if status == 404 else "failed")
    assert "HTTP %s" % status in result.detail and code in result.detail
    assert "private-server-message" not in result.detail
    assert result.data == payload
    if status == 429:
        assert "retry after 17 seconds" in result.detail
    get.assert_called_once()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("17", 17),
        ("0", 0),
        (None, None),
        ("private-secret", None),
        ("-1", None),
        ("1.5", None),
        ("١٧", None),
        ("9" * 200, None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0),
    ],
)
def test_retry_after_header_is_safe_and_bounded(value, expected):
    assert retry_delay(value) == expected


def test_nested_token_fields_preserve_raw_evidence_and_zero_tax():
    token = {
        "mint": MINT,
        "pool": "pool",
        "symbol": "TEST",
        "mode": "reward",
        "transferFee": {"bps": 0},
        "quote": {"mint": MINT, "category": "xstock", "symbol": "QUOTE"},
        "market": {"priceUsd": 0, "marketCapUsd": 10},
        "links": {"website": "https://project.example"},
        "website": "https://untrusted.example",
        "priceUsd": 999,
        "analytics": {"on_chain": {"status": "success"}},
        "unknown": {"preserve": True},
    }
    envelope = {"data": {"tokens": [token]}, "meta": {"generatedAt": "now"}}
    original = deepcopy(envelope)
    http = Mock(get_json=Mock(return_value=(envelope, None)))
    report = StonksSearcher(StonksClient(http)).search_query("TEST")
    pool = report.findings.tokens["pools"][0]
    assert pool["priceUsd"] == 0
    assert pool["transferTaxBps"] == 0
    assert pool["isRewardLaunch"] is True
    assert pool["quoteCategory"] == "xstock"
    assert pool["quoteSymbol"] == "QUOTE"
    assert pool["website"] == "https://project.example"
    assert "on_chain" not in pool["analytics"]
    assert report.raw == original == envelope


@pytest.mark.parametrize("field", ["market", "quote", "links", "transferFee"])
def test_malformed_nested_objects_fail_without_hiding_missing_data(field):
    token = {"mint": MINT, field: []}
    http = Mock(
        get_json=Mock(
            return_value=(
                {"data": {"tokens": [token]}},
                None,
            )
        )
    )
    with pytest.raises(ValueError, match="unexpected token shape"):
        StonksClient(http).get_pools()
    http.get_json.return_value = ({"data": {"token": token}}, None)
    assert StonksTokenClient(http).get_market(MINT).status == "failed"


@pytest.mark.parametrize("page_size", [0, 101, True, "10"])
def test_listing_rejects_bad_page_size_before_requests(page_size):
    http = Mock()
    with pytest.raises(ValueError):
        StonksClient(http).get_pools(page_size=page_size)
    http.get_json.assert_not_called()


def test_custom_holder_url_is_independent_of_public_api(monkeypatch):
    monkeypatch.setattr(settings, "STONKS_API_URL", "https://v1.example")
    monkeypatch.setattr(
        settings, "STONKS_HOLDERS_API_URL", "https://holders.example/snapshot"
    )
    http = Mock(
        get_json=Mock(
            return_value=(
                {
                    "mint": MINT,
                    "available": True,
                    "complete": True,
                    "holders": [],
                },
                None,
            )
        )
    )
    assert StonksTokenClient(http).get_holders(MINT).status == "success"
    http.get_json.assert_called_once_with(
        "https://holders.example/snapshot",
        params={"mint": MINT},
        source="Stonks",
    )


def test_json_search_exposes_safe_throttling_details(monkeypatch, capsys):
    monkeypatch.setattr(
        settings, "STONKS_API_URL", settings.DEFAULT_STONKS_API_URL
    )
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "search", "stonks", "TEST"]
    )
    get = Mock(
        return_value=Mock(
            ok=False,
            status_code=429,
            headers={"Retry-After": "17"},
            json=Mock(
                return_value={
                    "error": {
                        "code": "rate_limited",
                        "message": "private-server-message",
                    }
                }
            ),
        )
    )
    monkeypatch.setattr("requests.Session.get", get)
    assert growr.main() == 1
    captured = capsys.readouterr()
    document = validate(json.loads(captured.out))
    assert "rate_limited" in document["error"]["message"]
    assert "retry after 17 seconds" in document["error"]["message"]
    assert "private-server-message" not in captured.out
    assert captured.err == ""
    get.assert_called_once()


@pytest.mark.parametrize("mode", ["newest", "invalid"])
def test_listing_modes_remain_distinct_from_api_sort_names(mode):
    http = Mock()
    with pytest.raises(ValueError, match="listing mode"):
        StonksClient(http).get_pools(mode)
    http.get_json.assert_not_called()
