"""Subprocess activity and offline cohort analysis boundaries."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from growr_cli.playbooks import activity, shared_holdings
from growr_cli.playbooks.runner import GrowrRunner
from growr_cli.scanners.history import HistoryScanner
from tests.conftest import make_signature_record
from tests.test_history import ADDRESS, OTHER, SIGNATURE, transaction_body
from tests.test_machine import output_for
from tests.test_playbooks import child_commands


def history_document(address, signatures, limit=10):
    rpc = Mock()
    rpc.get_signatures.return_value = signatures
    report = HistoryScanner(rpc, "test").history(address, limit=limit)
    return output_for(report, "history", address, "--limit", str(limit))


def transaction_document(signature=SIGNATURE):
    rpc = Mock()
    rpc.get_transaction.return_value = transaction_body(signature)
    report = HistoryScanner(rpc, "test").transaction(signature)
    return output_for(report, "transaction", signature)


def test_activity_deduplicates_shared_signatures_across_addresses(monkeypatch):
    commands = child_commands(
        monkeypatch,
        {
            ("history", ADDRESS): history_document(
                ADDRESS, [make_signature_record()]
            ),
            ("history", OTHER): history_document(
                OTHER, [make_signature_record()]
            ),
            ("transaction", SIGNATURE): transaction_document(),
        },
    )
    options = activity.build_parser().parse_args(
        [ADDRESS, "--token-account", OTHER]
    )
    runner = GrowrRunner(30, 50)
    report = activity.investigate(options, runner)
    assert report["status"] == "success"
    assert commands.call_count == 3
    assert len(report["transactions"]) == 1
    assert len(report["transactions"][0]["references"]) == 2
    assert (
        report["transactions"][0]["transaction"]["events"][0]["raw_amount"]
        == "123"
    )


def test_activity_budget_keeps_refs_without_calling_more_children(monkeypatch):
    commands = child_commands(
        monkeypatch,
        {
            ("history", ADDRESS): history_document(
                ADDRESS, [make_signature_record()]
            ),
        },
    )
    options = activity.build_parser().parse_args(
        [ADDRESS, "--max-rpc-calls", "1"]
    )
    report = activity.investigate(options, GrowrRunner(30, 1))
    assert commands.call_count == 1
    assert report["status"] == "partial"
    assert report["transactions"][0]["detail_status"] == "budget_exhausted"
    assert report["transactions"][0]["transaction"] is None


@pytest.mark.parametrize(
    "corruption", ["scope", "cursor", "signature", "limit"]
)
def test_activity_rejects_invalid_child_history(monkeypatch, corruption):
    document = history_document(ADDRESS, [make_signature_record()])
    facts = document["records"][0]["facts"]
    if corruption == "scope":
        facts["scope"] = "all_wallet_history"
    elif corruption == "cursor":
        facts["pagination"]["next_before"] = str(
            make_signature_record(2).signature
        )
    elif corruption == "signature":
        facts["entries"][0]["signature"] = "private data"
    else:
        document["request"]["options"]["limit"] = 99
    child_commands(monkeypatch, {("history", ADDRESS): document})
    runner = GrowrRunner(30, 2)
    assert runner.history(ADDRESS) is None
    assert runner.scans[0]["error"] == "invalid_growr_output"
    assert "private data" not in json.dumps(runner.scans)


def test_activity_cli_json_has_only_report(monkeypatch, capsys):
    child_commands(
        monkeypatch, {("history", ADDRESS): history_document(ADDRESS, [])}
    )
    assert activity.main([ADDRESS, "--json"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["transactions"] == []
    assert output.err == ""


def cohort_report():
    wallets = []
    for owner, account in ((ADDRESS, ADDRESS), (OTHER, OTHER)):
        wallets.append(
            {
                "address": owner,
                "inventory_complete": True,
                "holdings": [
                    {
                        "mint": ADDRESS,
                        "token_program": "spl_token",
                        "raw_amount": "18446744073709551615",
                        "decimals": 9,
                        "amount_source": "rpc",
                        "accounts": [
                            {
                                "address": account,
                                "raw_amount": "18446744073709551615",
                                "state": "initialized",
                            }
                        ],
                    }
                ],
            }
        )
    return {
        "playbook_version": "1.1",
        "playbook": "token_holders",
        "target": ADDRESS,
        "status": "success",
        "wallets": wallets,
    }


def test_shared_holdings_exact_amounts_and_unknown_inventories():
    report = cohort_report()
    missing = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    report["wallets"].append(
        {"address": missing, "inventory_complete": False, "holdings": None}
    )
    result = shared_holdings.analyze(report)
    group = result["shared_holdings"][0]
    assert group["owner_count"] == 2
    assert group["selected_owner_count"] == 3
    assert group["unknown_presence"] == [missing]
    assert group["known_absent"] == []
    assert group["owners"][0]["amount_tokens"] == "18446744073.709551615"
    assert result["status"] == "partial"
    assert result["rpc_calls"] == 0


def test_shared_holdings_known_empty_is_distinct_from_unknown():
    report = cohort_report()
    absent = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    report["wallets"].append(
        {"address": absent, "inventory_complete": True, "holdings": []}
    )
    group = shared_holdings.analyze(report)["shared_holdings"][0]
    assert group["known_absent"] == [absent]
    assert group["unknown_presence"] == []


@pytest.mark.parametrize(
    "corruption", ["amount", "duplicate", "decimals", "null_complete"]
)
def test_shared_holdings_rejects_invalid_evidence(corruption):
    report = cohort_report()
    wallet = report["wallets"][0]
    if corruption == "amount":
        wallet["holdings"][0]["raw_amount"] = "1"
    elif corruption == "duplicate":
        report["wallets"].append(deepcopy(wallet))
    elif corruption == "decimals":
        wallet["holdings"][0]["decimals"] = True
    else:
        wallet["holdings"] = None
    with pytest.raises(ValueError):
        shared_holdings.analyze(report)


def test_saved_cohort_cli_is_offline(monkeypatch, tmp_path, capsys):
    path = tmp_path / "holders.json"
    path.write_text(json.dumps(cohort_report()))
    child = Mock(side_effect=AssertionError("offline only"))
    monkeypatch.setattr("subprocess.run", child)
    assert shared_holdings.main([str(path), "--json"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["rpc_calls"] == 0
    assert output.err == ""
    child.assert_not_called()


def test_saved_cohort_rejects_invalid_json_safely(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text('{"secret": NaN}')
    assert shared_holdings.main([str(path), "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"] == "invalid_saved_report"
    assert "secret" not in output.out
