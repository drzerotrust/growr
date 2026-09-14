"""Stonkfun token scans, source selection and endpoint coverage."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

import growr
from growr_cli import settings
from growr_cli.integrations.stonks_token import (
    StonksTokenClient,
    market_summary,
)
from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID
from tests.conftest import make_mint_bytes
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import validate


@pytest.fixture
def payloads():
    total = {
        "mint": MINT,
        "decimals": 9,
        "amountRaw": "138711402669695002",
        "amountTokens": 138711402.66969502,
        "valueUsdAtBurn": 4358386.46,
        "burnCount": 11499,
        "lastBurnAt": "2026-09-09T23:28:14.958Z",
    }
    return {
        "market": {
            "data": {
                "token": {
                    "mint": MINT,
                    "symbol": "STOCK",
                    "name": "Example Stonk",
                    "pool": "original-pool",
                    "market": {
                        "priceUsd": 0,
                        "marketCapUsd": 172973171.26,
                        "volume24hUsd": 1880579.21,
                    },
                    "quote": {"category": "xstock"},
                },
                "launch": {"mint": MINT},
            },
            "meta": {"generatedAt": "2026-09-12T16:00:00Z"},
        },
        "token-holders": {
            "mint": MINT,
            "available": True,
            "complete": True,
            "decimals": 9,
            "supplyTokens": 861320792.66,
            "holderCount": 41616,
            "holders": [
                {
                    "rank": rank,
                    "address": "holder-%02d" % rank,
                    "amountTokens": 1000,
                    "supplyPct": 0.1,
                }
                for rank in range(1, 13)
            ],
        },
        "rewards": {
            "data": {
                "mint": MINT,
                "mode": "reward",
                "quote": {"mint": OTHER, "symbol": "REWARD", "decimals": 9},
                "rewards": {
                    "distributedRaw": "587560606644862",
                    "distributedTokens": 587560.606644862,
                    "undistributedRaw": "280",
                    "undistributedTokens": 0.00000028,
                    "payoutCount": 29571,
                    "holderCount": 2467,
                    "lastPayoutAt": "2026-09-13T18:39:28.841Z",
                },
            },
            "meta": {"generatedAt": "2026-09-13T18:46:21.520Z"},
        },
        "burns": {
            "data": {
                "mint": MINT,
                "totals": total,
                "burns": [
                    {
                        "signature": "sample-signature",
                        "amountTokens": 0,
                        "source": "quote-revenue",
                        "valueUsdAtBurn": 0,
                        "burnedAt": "2026-09-09T23:28:14.958Z",
                    },
                ],
            },
            "meta": {"generatedAt": "2026-09-12T16:00:00Z"},
        },
    }


@pytest.fixture
def stonks_io(monkeypatch, payloads):
    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_account_data.side_effect = [
        (make_mint_bytes(), str(SPL_TOKEN_PROGRAM_ID)),
        (None, None),
    ]
    rpc.find_metadata_address.return_value = Pubkey.from_string(OTHER)
    rpc.get_largest_token_accounts.return_value = []
    rpc.get_multiple_accounts.return_value = []
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))

    def get(url, **options):
        paths = {
            "%s/tokens/%s" % (settings.STONKS_API_URL, MINT): "market",
            "%s/tokens/%s/burns" % (settings.STONKS_API_URL, MINT): "burns",
            settings.STONKS_HOLDERS_API_URL: "token-holders",
            (
                "%s/tokens/%s/rewards" % (settings.STONKS_API_URL, MINT)
            ): "rewards",
        }
        endpoint = paths[url]
        params = {"mint": MINT} if endpoint == "token-holders" else None
        assert options["params"] == params
        assert options["timeout"] > 0
        body = payloads[endpoint]
        missing = isinstance(body, dict) and "error" in body
        return Mock(
            ok=not missing,
            status_code=404 if missing else 200,
            json=Mock(return_value=body),
        )

    http_get = Mock(side_effect=get)
    monkeypatch.setattr("requests.Session.get", http_get)
    # Disabled providers must not block startup or create clients.
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "your_jupiter_api_key")
    for name in ("JUPITER_API_URL", "RUGCHECK_API_URL"):
        monkeypatch.setattr(settings, name, "unused-invalid-endpoint")
    for name in ("JupiterClient", "RugcheckClient"):
        monkeypatch.setattr(
            growr, name, Mock(side_effect=AssertionError("Unused provider"))
        )
    return rpc, http_get


@pytest.mark.parametrize(
    "flags", [[], ["--json"], ["--json", "--include-raw", "--verbose"]]
)
def test_stonks_cli_fetches_four_endpoints_and_preserves_rpc(
    monkeypatch, capsys, payloads, stonks_io, flags
):
    original = deepcopy(payloads)
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "token", MINT, "--stonk"]
    )

    assert growr.main() == 0

    output = capsys.readouterr()
    assert bool(output.err) == ("--verbose" in flags)
    assert "holder-01" not in output.err
    rpc, http_get = stonks_io
    rpc.close.assert_called_once()
    assert http_get.call_count == 4
    assert payloads == original
    if "--json" not in flags:
        assert "STOCK" in output.out
        assert "WRONG" not in output.out
        assert "Stonks reported holders" in output.out
        assert "holder-10" in output.out and "holder-11" not in output.out
        assert "Stonks burns (USD valued at burn time)" in output.out
        assert "Stonks (holders): SUCCESS" in output.out
        return

    document = validate(json.loads(output.out))
    assert document["status"] == "success"
    assert document["request"]["command"] == "token"
    assert document["request"]["options"]["stonk"] is True
    assert document["request"]["options"]["jupiter"] is False
    assert document["request"]["options"]["rugcheck"] is False
    record = document["records"][0]
    assert record["facts"]["source"] == "rpc"
    assert record["facts"]["mint"]["supply"] == "1000"
    assert "stonks_holders" not in record["facts"]
    metrics = record["metrics"]
    assert metrics["stonks_market"]["source"] == "stonks"
    assert metrics["stonks_market"]["values"]["price_usd"] == 0
    assert metrics["stonks_holders"]["values"]["holder_count"] == 41616
    assert len(metrics["stonks_holders"]["values"]["holders"]) == 12
    burns = metrics["stonks_burns"]["values"]
    assert burns["totals"]["raw_amount"] == "138711402669695002"
    assert burns["totals"]["burn_count"] == 11499
    assert "all_totals" not in burns and "buyback_totals" not in burns
    assert "raw_amount" not in burns["recent"][0]
    assert burns["recent"][0]["amount_tokens"] == 0
    assert burns["recent"][0]["source"] == "quote-revenue"
    outcomes = {
        (item["source"], item["operation"]): item
        for item in record["coverage"]
    }
    for operation in ("market", "holders", "burns", "rewards"):
        assert outcomes["stonks", operation]["status"] == "success"
        assert outcomes["stonks", operation]["fetched_at"]
    for source in ("jupiter", "rugcheck"):
        assert outcomes[source, "token_context"]["status"] == "skipped"
    if "--include-raw" in flags:
        assert record["raw"]["stonks_market"] == original["market"]
        assert record["raw"]["stonks_holders"] == original["token-holders"]
        assert record["raw"]["stonks_burns"] == original["burns"]
        assert record["raw"]["stonks_rewards"] == original["rewards"]
    else:
        assert "raw" not in record


@pytest.mark.parametrize(
    ("endpoint", "replacement", "operation", "status"),
    [
        ("market", {"error": "bad"}, "market", "failed"),
        ("market", {"error": {"code": "not_found"}}, "market", "no_data"),
        (
            "token-holders",
            {"mint": MINT, "available": False},
            "holders",
            "failed",
        ),
        ("token-holders", "incomplete", "holders", "partial"),
        ("burns", {"data": {"mint": OTHER, "burns": []}}, "burns", "failed"),
        (
            "burns",
            {"data": {"mint": MINT, "totals": None, "burns": []}},
            "burns",
            "no_data",
        ),
    ],
)
def test_stonks_endpoint_gaps_keep_other_results(
    monkeypatch,
    capsys,
    payloads,
    stonks_io,
    endpoint,
    replacement,
    operation,
    status,
):
    if replacement == "incomplete":
        payloads[endpoint]["complete"] = False
    else:
        payloads[endpoint] = replacement
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "token", MINT, "--stonk"]
    )

    assert growr.main() == 0

    output = capsys.readouterr()
    assert output.err == ""
    document = validate(json.loads(output.out))
    assert document["status"] == (
        "success" if status == "no_data" else "partial"
    )
    record = document["records"][0]
    outcomes = {
        item["operation"]: item["status"]
        for item in record["coverage"]
        if item["source"] == "stonks"
    }
    assert outcomes.pop(operation) == status
    assert set(outcomes.values()) == {"success"}
    assert record["facts"]["mint"]["supply"] == "1000"
    if status == "partial":
        assert (
            record["metrics"]["stonks_holders"]["values"]["complete"] is False
        )
    stonks_io[0].close.assert_called_once()


@pytest.mark.parametrize(
    "method", ["get_market", "get_holders", "get_burns", "get_rewards"]
)
@pytest.mark.parametrize("payload", [None, [], {"error": "bad response"}])
def test_stonks_rejects_malformed_responses(method, payload):
    client = StonksTokenClient(
        Mock(get_json=Mock(return_value=(payload, None)))
    )
    assert getattr(client, method)(MINT).status == "failed"


@pytest.mark.parametrize(
    "method", ["get_market", "get_holders", "get_burns", "get_rewards"]
)
def test_stonks_http_failures_are_explicit(method):
    client = StonksTokenClient(
        Mock(get_json=Mock(return_value=(None, "Stonks returned HTTP 503")))
    )
    result = getattr(client, method)(MINT)
    assert result.status == "failed"
    assert result.detail == "Stonks returned HTTP 503"


def test_market_rejects_mismatched_mint_and_preserves_single_pool(payloads):
    data = payloads["market"]
    summary = market_summary(data, MINT)
    assert summary["pool_count"] == 1
    assert summary["pools"][0]["pool"] == "original-pool"
    data["data"]["token"]["mint"] = OTHER
    client = StonksTokenClient(Mock(get_json=Mock(return_value=(data, None))))
    assert client.get_market(MINT).status == "failed"


def test_stonks_configuration_fails_before_creating_clients(
    monkeypatch, capsys
):
    monkeypatch.setattr(settings, "STONKS_API_URL", "invalid-endpoint")
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "token", MINT, "--stonk"]
    )
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 1
    report = validate(json.loads(capsys.readouterr().out))
    assert "STONKS_API_URL" in report["error"]["message"]
    http.assert_not_called()


@pytest.mark.parametrize("raw_amount", [123, "1.5", "-1", "", True])
def test_burn_base_units_must_be_decimal_strings(payloads, raw_amount):
    payloads["burns"]["data"]["totals"]["amountRaw"] = raw_amount
    client = StonksTokenClient(
        Mock(get_json=Mock(return_value=(payloads["burns"], None)))
    )
    assert client.get_burns(MINT).status == "failed"


@pytest.mark.parametrize("group", ["totals", "burns"])
def test_burns_never_accept_another_mint_inside_the_response(payloads, group):
    item = payloads["burns"]["data"][group]
    item = item[0] if isinstance(item, list) else item
    item["mint"] = OTHER
    client = StonksTokenClient(
        Mock(get_json=Mock(return_value=(payloads["burns"], None)))
    )
    assert client.get_burns(MINT).status == "failed"


def test_zero_holders_is_available_data(payloads):
    data = payloads["token-holders"]
    data.update(holderCount=0, holders=[])
    client = StonksTokenClient(Mock(get_json=Mock(return_value=(data, None))))
    result = client.get_holders(MINT)
    assert result.status == "success"
    assert result.data["holderCount"] == 0


@pytest.mark.parametrize("command", ["wallet", "token-account"])
def test_stonk_token_flag_is_rejected_for_other_scans(
    monkeypatch, capsys, command
):
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", command, MINT, "--stonk"]
    )
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 2
    document = validate(json.loads(capsys.readouterr().out))
    assert document["error"]["code"] == "INVALID_ARGUMENTS"
    http.assert_not_called()


@pytest.mark.parametrize(
    "flags", [[], ["--json"], ["--json", "--include-raw"]]
)
def test_reward_comparison_cli_keeps_rpc_and_input_file(
    monkeypatch, capsys, tmp_path, payloads, stonks_io, flags
):
    from tests.test_rewards import reward_document

    previous = deepcopy(payloads["rewards"])
    previous["meta"]["generatedAt"] = "2026-09-12T18:46:21.520Z"
    raw = previous["data"]["rewards"]["distributedRaw"]
    previous["data"]["rewards"]["distributedRaw"] = str(int(raw) - 1000000000)
    path = tmp_path / "private reward snapshot.json"
    path.write_text(json.dumps(reward_document(previous)))
    before = path.read_bytes()
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            *flags,
            "token",
            MINT,
            "--stonk",
            "--compare-to",
            str(path),
        ],
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    assert path.read_bytes() == before
    assert path.name not in output.out + output.err
    assert output.err == ""
    assert stonks_io[1].call_count == 4
    stonks_io[0].close.assert_called_once()
    if "--json" not in flags:
        assert "Stonks rewards (coin-wide totals)" in output.out
        assert "Tokens Distributed During Interval: 1" in output.out
        assert "Normalized Tokens Per 24 Hours: 1" in output.out
        assert "not a calendar-day payout" in output.out
        return
    document = validate(json.loads(output.out))
    assert document["status"] == "success"
    assert document["request"]["options"]["compare_rewards"] is True
    record = document["records"][0]
    assert record["facts"]["source"] == "rpc"
    assert "stonks_rewards" not in record["facts"]
    assert "reward_comparison" not in record["facts"]
    comparison = record["metrics"]["reward_comparison"]
    assert comparison["source"] == "growr"
    assert comparison["values"]["distributed_delta_raw"] == "1000000000"
    assert comparison["values"]["distributed_delta_tokens"] == "1"
    assert comparison["values"]["normalized_daily_tokens"] == "1"
    assert comparison["values"]["elapsed_seconds"] == 86400
    assert record["metrics"]["stonks_rewards"]["source"] == "stonks"
    if "--include-raw" in flags:
        assert record["raw"]["stonks_rewards"] == payloads["rewards"]
        assert set(record["raw"]) == {
            "stonks_market",
            "stonks_holders",
            "stonks_burns",
            "stonks_rewards",
        }


@pytest.mark.parametrize(
    "failure", ["http", "standard", "cached", "time", "counter"]
)
def test_unavailable_comparison_retains_current_scan(
    monkeypatch, capsys, tmp_path, payloads, stonks_io, failure
):
    from tests.test_rewards import reward_document

    previous = deepcopy(payloads["rewards"])
    previous["meta"]["generatedAt"] = "2026-09-12T18:46:21.520Z"
    path = tmp_path / "previous.json"
    path.write_text(json.dumps(reward_document(previous)))
    if failure == "http":
        payloads["rewards"] = {"error": {"code": "service_unavailable"}}
    elif failure == "standard":
        payloads["rewards"]["data"].update(mode="standard", rewards=None)
    elif failure == "cached":
        payloads["rewards"] = previous
    elif failure == "time":
        payloads["rewards"]["meta"] = {}
    else:
        payloads["rewards"]["data"]["rewards"]["distributedRaw"] = "0"
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            "--json",
            "token",
            MINT,
            "--stonk",
            "--compare-to",
            str(path),
        ],
    )
    assert growr.main() == 0
    document = validate(json.loads(capsys.readouterr().out))
    assert document["status"] == "partial"
    record = document["records"][0]
    assert record["facts"]["mint"]["supply"] == "1000"
    assert "stonks_market" in record["metrics"]
    assert "stonks_burns" in record["metrics"]
    assert "reward_comparison" not in record["metrics"]
    outcomes = {
        item["operation"]: item["status"] for item in record["coverage"]
    }
    assert outcomes["reward_comparison"] == "failed"
    if failure == "standard":
        assert outcomes["rewards"] == "no_data"
    elif failure not in {"http", "standard"}:
        assert "stonks_rewards" in record["metrics"]


def test_standard_coin_rewards_are_no_data_without_comparison(
    monkeypatch, capsys, payloads, stonks_io
):
    payloads["rewards"]["data"].update(mode="standard", rewards=None)
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "token", MINT, "--stonk"]
    )
    assert growr.main() == 0
    document = validate(json.loads(capsys.readouterr().out))
    assert document["status"] == "success"
    assert "stonks_rewards" not in document["records"][0]["metrics"]
    assert document["request"]["options"]["compare_rewards"] is False


@pytest.mark.parametrize(
    "command",
    [
        ["token", MINT],
        ["token", MINT, "--stonk"],
        ["wallet", MINT],
        ["list", "stonks"],
        ["search", "stonks", "te"],
    ],
)
@pytest.mark.parametrize("flags", [[], ["--json"]])
def test_bad_comparison_arguments_fail_before_clients(
    monkeypatch, capsys, tmp_path, command, flags
):
    path = tmp_path / "private-comparison-file.json"
    path.write_text("not-json-private-content")
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            *flags,
            *command,
            "--compare-to",
            str(path),
        ],
    )
    http = Mock()
    rpc = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    if "--json" in flags:
        assert growr.main() == 2
        output = capsys.readouterr()
        assert (
            validate(json.loads(output.out))["error"]["code"]
            == "INVALID_ARGUMENTS"
        )
        assert path.name not in output.out and output.err == ""
    else:
        with pytest.raises(SystemExit) as error:
            growr.main()
        assert error.value.code == 2
        assert "not-json-private-content" not in capsys.readouterr().err
    http.assert_not_called()
    rpc.assert_not_called()
