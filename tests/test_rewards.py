"""Reward units, saved report validation and interval semantics."""

import json
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal, localcontext
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError

from growr_cli.analysis.rewards import compare_rewards, token_amount
from growr_cli.integrations.stonks_rewards import get_rewards, rewards_summary
from growr_cli.machine.comparison import load_reward_snapshot
from growr_cli.models import ProviderStatus, ScanReport
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import output_for, validate

STAMP = "2026-09-13T12:00:00Z"
PREVIOUS = "2026-09-12T12:00:00Z"


def reward_payload(raw="123456789012345678901234567890", stamp=STAMP):
    return {
        "data": {
            "mint": MINT,
            "mode": "reward",
            "quote": {"mint": OTHER, "symbol": "USD", "decimals": 9},
            "rewards": {
                "distributedRaw": raw,
                "distributedTokens": 999,
                "undistributedRaw": "0",
                "payoutCount": 0,
                "holderCount": 0,
                "lastPayoutAt": None,
            },
        },
        "meta": {"generatedAt": stamp},
    }


def reward_document(payload=None):
    payload = payload or reward_payload(stamp=PREVIOUS)
    result = get_rewards(
        Mock(get_json=Mock(return_value=(payload, None))), MINT
    )
    report = ScanReport("token", MINT, "test", PREVIOUS)
    report.summary["stonks_rewards"] = rewards_summary(payload, MINT)
    report.provider_data["stonks_rewards"] = asdict(result)
    report.providers.append(ProviderStatus("Stonks", "success", "", "rewards"))
    return output_for(report, "token", MINT, "--stonk")


@pytest.mark.parametrize(
    ("raw", "decimals", "expected"),
    [
        ("0", 9, "0"),
        ("1", 9, "0.000000001"),
        ("1000000000", 9, "1"),
        ("123", 0, "123"),
        (
            "123456789012345678901234567890",
            9,
            "123456789012345678901.23456789",
        ),
    ],
)
def test_native_amounts_remain_exact_under_small_decimal_context(
    raw, decimals, expected
):
    with localcontext() as context:
        context.prec = 3
        assert token_amount(raw, decimals) == expected


@pytest.mark.parametrize(
    ("raw", "decimals"),
    [
        (1, 9),
        (True, 9),
        ("-1", 9),
        ("1.5", 9),
        ("١", 9),
        ("", 9),
        ("1", True),
        ("1", -1),
        ("1", 256),
    ],
)
def test_invalid_units_are_rejected(raw, decimals):
    with pytest.raises(ValueError):
        token_amount(raw, decimals)


def test_reward_totals_preserve_raw_payload_and_use_exact_base_units():
    payload = reward_payload()
    original = deepcopy(payload)
    result = get_rewards(
        Mock(get_json=Mock(return_value=(payload, None))), MINT
    )
    assert result.status == "success"
    assert result.data == original == payload
    summary = rewards_summary(result.data, MINT)
    assert summary["distributed_tokens"] == "123456789012345678901.23456789"
    assert summary["undistributed_tokens"] == "0"
    assert summary["payout_count"] == summary["holder_count"] == 0
    assert summary["last_payout_at"] is None
    validate(reward_document(payload))


@pytest.mark.parametrize("mode", ["standard", "reward"])
def test_null_rewards_are_only_normal_for_standard_mode(mode):
    payload = {"data": {"mint": MINT, "mode": mode, "rewards": None}}
    result = get_rewards(
        Mock(get_json=Mock(return_value=(payload, None))), MINT
    )
    assert result.status == ("no_data" if mode == "standard" else "failed")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("data", "mint"), OTHER),
        (("data", "quote", "mint"), "not-a-mint"),
        (("data", "quote", "decimals"), True),
        (("data", "quote", "symbol"), []),
        (("data", "rewards", "distributedRaw"), 123),
        (("data", "rewards", "undistributedRaw"), "-1"),
        (("data", "rewards", "payoutCount"), True),
        (("data", "rewards", "holderCount"), -1),
        (("data", "rewards"), []),
    ],
)
def test_invalid_reward_payloads_fail_the_endpoint(path, value):
    payload = reward_payload()
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    result = get_rewards(
        Mock(get_json=Mock(return_value=(payload, None))), MINT
    )
    assert result.status == "failed"
    assert result.data == payload


@pytest.mark.parametrize(
    ("end", "seconds", "expected"),
    [
        (STAMP, 86400, "1"),
        ("2026-09-12T18:00:00Z", 21600, "4"),
        ("2026-09-14T12:00:00Z", 172800, "0.5"),
        ("2026-09-12T12:00:00.500000Z", 0.5, "172800"),
    ],
)
def test_interval_uses_provider_time_and_normalizes_daily_rate(
    end, seconds, expected
):
    previous = rewards_summary(reward_payload("1000000000", PREVIOUS), MINT)
    current = rewards_summary(reward_payload("2000000000", end), MINT)
    result = compare_rewards(previous, current)
    assert result["elapsed_seconds"] == seconds
    assert result["distributed_delta_raw"] == "1000000000"
    assert result["distributed_delta_tokens"] == "1"
    assert Decimal(result["normalized_daily_tokens"]) == Decimal(expected)


def test_difference_keeps_one_base_unit_between_large_totals():
    raw = "999999999999999999999999999999999999"
    previous = rewards_summary(reward_payload(raw, PREVIOUS), MINT)
    current = rewards_summary(reward_payload(str(int(raw) + 1)), MINT)
    result = compare_rewards(previous, current)
    assert result["distributed_delta_raw"] == "1"
    assert result["distributed_delta_tokens"] == "0.000000001"
    assert result["normalized_daily_tokens"] == "0.000000001"


def test_daily_division_has_28_significant_digits():
    previous = rewards_summary(reward_payload("0", PREVIOUS), MINT)
    current = rewards_summary(
        reward_payload("1000000000", "2026-09-15T12:00:00Z"), MINT
    )
    assert compare_rewards(previous, current)["normalized_daily_tokens"] == (
        "0.3333333333333333333333333333"
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("provider_generated_at", PREVIOUS),
        ("provider_generated_at", "2026-09-12T06:00:00-06:00"),
        ("provider_generated_at", "2026-09-11T12:00:00Z"),
        ("provider_generated_at", None),
        ("provider_generated_at", "2026-09-13T12:00:00"),
        ("distributed_raw", "0"),
        ("reward_mint", MINT),
        ("mint", OTHER),
        ("decimals", 6),
    ],
)
def test_uncomparable_snapshots_do_not_produce_numbers(key, value):
    previous = rewards_summary(reward_payload("100", PREVIOUS), MINT)
    current = rewards_summary(reward_payload("200"), MINT)
    current[key] = value
    with pytest.raises(ValueError):
        compare_rewards(previous, current)


def test_missing_provider_time_keeps_totals_but_cannot_be_compared():
    payload = reward_payload(stamp=None)
    result = get_rewards(
        Mock(get_json=Mock(return_value=(payload, None))), MINT
    )
    assert result.status == "success"
    assert rewards_summary(payload, MINT)["provider_generated_at"] is None


def test_file_round_trip_uses_normal_report_without_raw(tmp_path):
    document = reward_document()
    path = tmp_path / "previous.json"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    snapshot = load_reward_snapshot(path, MINT)
    assert snapshot["mint"] == MINT
    assert snapshot["provider_generated_at"] == "2026-09-12T12:00:00+00:00"
    assert path.read_bytes() == before
    assert "raw" not in document["records"][0]
    assert "reward_symbol" not in snapshot


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "2.1"),
        (("status",), "error"),
        (("tool",), []),
        (("request", "command"), "search"),
        (("request", "target"), OTHER),
        (("request", "options", "stonk"), False),
        (("records",), []),
        (("records", 0, "kind"), "wallet"),
        (("records", 0, "identity"), None),
        (("records", 0, "identity", "mint"), OTHER),
        (("records", 0, "identity", "address"), OTHER),
        (("records", 0, "metrics"), []),
        (("records", 0, "metrics", "stonks_rewards", "source"), "rpc"),
        (("records", 0, "metrics", "stonks_rewards", "values"), None),
        (("records", 0, "metrics", "stonks_rewards", "values", "mint"), OTHER),
        (
            (
                "records",
                0,
                "metrics",
                "stonks_rewards",
                "values",
                "provider_generated_at",
            ),
            None,
        ),
        (("records", 0, "coverage"), []),
        (
            ("records", 0, "coverage"),
            [
                {
                    "source": "stonks",
                    "operation": "rewards",
                    "status": "failed",
                }
            ],
        ),
    ],
)
def test_invalid_saved_reports_are_rejected_without_echoing_data(
    tmp_path, path, value
):
    document = reward_document()
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    file = tmp_path / "private-snapshot-name.json"
    file.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Invalid --compare-to") as error:
        load_reward_snapshot(file, MINT)
    assert "private-snapshot-name" not in str(error.value)


@pytest.mark.parametrize("contents", ["", "not-json-secret", "{", "NaN", "[]"])
def test_unreadable_snapshot_contents_are_safe(tmp_path, contents):
    path = tmp_path / "private-name.json"
    path.write_text(contents)
    with pytest.raises(ValueError) as error:
        load_reward_snapshot(path, MINT)
    assert "not-json-secret" not in str(error.value)
    assert "private-name" not in str(error.value)


def test_missing_snapshot_is_an_input_failure(tmp_path):
    with pytest.raises(ValueError, match="Invalid --compare-to"):
        load_reward_snapshot(tmp_path / "missing.json", MINT)


def test_partial_report_with_successful_rewards_can_be_reused(tmp_path):
    document = reward_document()
    document["status"] = "partial"
    document["records"][0]["coverage"].append(
        {
            "source": "stonks",
            "operation": "holders",
            "status": "failed",
            "detail": "Unavailable",
            "fetched_at": None,
        }
    )
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(document))
    assert load_reward_snapshot(path, MINT)["mode"] == "reward"


def test_conflicting_reward_coverage_cannot_supply_a_baseline(tmp_path):
    document = reward_document()
    outcomes = document["records"][0]["coverage"]
    rewards = next(item for item in outcomes if item["operation"] == "rewards")
    outcomes.append({**rewards, "status": "failed"})
    path = tmp_path / "conflicting.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Invalid --compare-to"):
        load_reward_snapshot(path, MINT)


def test_reward_schema_rejects_floating_native_amount():
    document = reward_document()
    values = document["records"][0]["metrics"]["stonks_rewards"]["values"]
    values["distributed_tokens"] = 1.5
    with pytest.raises(ValidationError):
        validate(document)
