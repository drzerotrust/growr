"""Jupiter batching, unit precedence and metadata evidence."""

import json
import subprocess
from copy import deepcopy
from unittest.mock import Mock

import pytest
from spl.token.constants import TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID

from growr_cli.searchers.jupiter import JupiterTokenSearcher
from scripts.playbooks import token_holders, wallet_holdings
from scripts.playbooks.runner import GrowrRunner
from tests.test_machine import output_for
from tests.test_playbooks import (
    MINT,
    OTHER_MINT,
    OWNER,
    SECOND_OWNER,
    THIRD_MINT,
    account,
    address,
    child_commands,
    holder,
    token_document,
    wallet_document,
)


def jupiter_token(mint=MINT, decimals=2, **fields):
    return {
        "id": mint,
        "name": "Example Jupiter",
        "symbol": "EXJ",
        "decimals": decimals,
        "tokenProgram": str(TOKEN_PROGRAM_ID),
        "icon": "https://project.example/icon.png",
        "website": "https://project.example",
        "twitter": "https://x.com/project",
        "usdPrice": 0,
        "isVerified": False,
        "updatedAt": "2026-09-14T12:00:00Z",
        **fields,
    }


def search_document(mints, tokens):
    query = ",".join(mints)
    client = Mock(discover=Mock(return_value=tokens))
    report = JupiterTokenSearcher(client).search("search", query=query)
    return output_for(report, "search", "jupiter", query)


def test_default_enrichment_shares_metadata_across_wallets(
    monkeypatch, capsys
):
    query = ",".join([MINT, OTHER_MINT])
    process = child_commands(
        monkeypatch,
        {
            ("token", MINT): token_document(
                holders=[holder(10, OWNER, 123), holder(11, SECOND_OWNER, 12)]
            ),
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 123), account(12, OTHER_MINT, 456)]
            ),
            ("wallet", SECOND_OWNER): wallet_document(
                SECOND_OWNER,
                [account(11, MINT, 12), account(13, OTHER_MINT, 1)],
            ),
            ("search", query): search_document(
                [MINT, OTHER_MINT],
                [jupiter_token(OTHER_MINT, 3), jupiter_token()],
            ),
        },
    )
    assert token_holders.main([MINT, "--json"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == ""
    assert report["status"] == "success"
    assert process.call_count == 4
    assert process.call_args.args[0][4:] == ["search", "jupiter", query]
    target, other = report["wallets"][0]["holdings"]
    assert target["amount_source"] == "rpc"
    assert other["amount_source"] == "jupiter"
    assert other["amount_tokens"] == "0.456"
    assert other["metadata"] == report["metadata_lookups"][OTHER_MINT]
    assert report["wallets"][1]["holdings"][1]["amount_tokens"] == "0.001"
    assert other["name"] == "Example Jupiter"
    assert other["symbol"] == "EXJ"
    assert other["metadata"]["icon"] == "https://project.example/icon.png"
    assert other["metadata"]["verified"] is False
    assert other["metadata"]["price_usd"] == 0
    assert len(other["metadata"]["social"]["links"]) == 2
    assert other["metadata"]["scan_index"] == 3
    assert report["budget"]["additional_mints_attempted"] == 0
    assert report["budget"]["rpc_calls_upper_estimate"] == 12
    assert report["budget"]["provider_http_requests_upper_estimate"] == 1
    assert report["scans"][3]["coverage"][0]["source"] == "jupiter"


@pytest.mark.parametrize("limit", [1, 2])
def test_batches_stop_at_100_and_preserve_unrequested_holdings(
    monkeypatch, capsys, limit
):
    mints = [address(index) for index in range(1, 102)]
    documents = {
        ("wallet", OWNER): wallet_document(
            entries=[
                account(index, mint, 1) for index, mint in enumerate(mints)
            ]
        ),
    }
    for offset in range(limit):
        batch = mints[offset * 100 : (offset + 1) * 100]
        documents[("search", ",".join(batch))] = search_document(
            batch, [jupiter_token(mint, 0) for mint in batch]
        )
    process = child_commands(monkeypatch, documents)
    assert (
        wallet_holdings.main(
            [OWNER, "--json", "--jupiter-batch-limit", str(limit)]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    holdings = report["wallets"][0]["holdings"]
    assert len(holdings) == 101
    assert holdings[-1]["raw_amount"] == "1"
    assert holdings[-1]["metadata"]["status"] == (
        "success" if limit == 2 else "budget_exhausted"
    )
    assert holdings[-1]["amount_tokens"] == ("1" if limit == 2 else None)
    assert report["status"] == ("success" if limit == 2 else "partial")
    assert process.call_count == 1 + limit
    assert report["budget"]["rpc_calls_upper_estimate"] == 4
    assert report["budget"]["jupiter_batches_attempted"] == limit


@pytest.mark.parametrize(
    "fields,conflict",
    [
        ({"decimals": 9}, "decimals"),
        ({"tokenProgram": str(TOKEN_2022_PROGRAM_ID)}, "token_program"),
    ],
)
def test_rpc_target_decimals_win_with_explicit_jupiter_conflict(
    monkeypatch, capsys, fields, conflict
):
    child_commands(
        monkeypatch,
        {
            ("token", MINT): token_document(holders=[holder(10, OWNER, 123)]),
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 123)]
            ),
            ("search", MINT): search_document(
                [MINT], [jupiter_token(**fields)]
            ),
        },
    )
    assert token_holders.main([MINT, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    assert holding["amount_tokens"] == "1.23"
    assert holding["amount_source"] == "rpc"
    assert holding["metadata_conflicts"] == [conflict]
    assert report["status"] == "partial"


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"decimals": None}, "missing_decimals"),
        ({"decimals": True}, "invalid_decimals"),
        ({"decimals": 2.0}, "invalid_decimals"),
        ({"decimals": -1}, "invalid_decimals"),
        ({"decimals": 256}, "invalid_decimals"),
        ({"tokenProgram": None}, "unknown_token_program"),
        ({"tokenProgram": []}, "unknown_token_program"),
        ({"tokenProgram": str(TOKEN_2022_PROGRAM_ID)}, "program_mismatch"),
    ],
)
def test_invalid_jupiter_units_keep_names_and_raw_balances(
    monkeypatch, capsys, fields, reason
):
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 123)]
            ),
            ("search", MINT): search_document(
                [MINT], [jupiter_token(**fields)]
            ),
        },
    )
    assert wallet_holdings.main([OWNER, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    assert holding["name"] == "Example Jupiter"
    assert holding["raw_amount"] == "123"
    assert holding["amount_tokens"] is None
    assert holding["amount_source"] is None
    assert holding["amount_status"] == reason
    assert report["status"] == "partial"


@pytest.mark.parametrize("decimals", [0, 255])
def test_jupiter_units_are_exact_for_token_2022(monkeypatch, capsys, decimals):
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 1, "token_2022")]
            ),
            ("search", MINT): search_document(
                [MINT],
                [
                    jupiter_token(
                        decimals=decimals,
                        tokenProgram=str(TOKEN_2022_PROGRAM_ID),
                    )
                ],
            ),
        },
    )
    assert wallet_holdings.main([OWNER, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    assert holding["amount_tokens"] == (
        "0." + "0" * 254 + "1" if decimals else "1"
    )
    assert holding["amount_source"] == "jupiter"


def test_optional_rpc_fallback_only_spends_budget_on_missing_units(
    monkeypatch, capsys
):
    mints = [MINT, OTHER_MINT, THIRD_MINT]
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[
                    account(10, MINT, 123),
                    account(11, OTHER_MINT, 456),
                    account(12, THIRD_MINT, 789),
                ]
            ),
            ("search", ",".join(mints)): search_document(
                mints,
                [
                    jupiter_token(),
                    jupiter_token(OTHER_MINT, None),
                ],
            ),
            ("token", OTHER_MINT): token_document(OTHER_MINT, decimals=3),
        },
    )
    assert wallet_holdings.main([OWNER, "--json", "--mint-limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    first, second, third = report["wallets"][0]["holdings"]
    assert first["amount_source"] == "jupiter"
    assert second["amount_source"] == "rpc"
    assert second["amount_tokens"] == "0.456"
    assert second["name"] == "Example Jupiter"
    assert third["metadata"]["status"] == "no_data"
    assert third["amount_status"] == "budget_exhausted"
    assert report["budget"]["additional_mints_attempted"] == 1
    assert report["budget"]["rpc_calls_upper_estimate"] == 8
    assert report["budget"]["provider_http_requests_upper_estimate"] == 1


@pytest.mark.parametrize("failure", ["empty", "timeout", "invalid", "exit"])
def test_missing_metadata_preserves_wallet_and_does_not_leak_diagnostics(
    monkeypatch, capsys, failure
):
    results = {
        "empty": search_document([MINT], []),
        "timeout": subprocess.TimeoutExpired("private", 30, "secret"),
        "invalid": subprocess.CompletedProcess([], 0, "secret", "secret"),
        "exit": subprocess.CompletedProcess([], 2, "secret", "secret"),
    }
    process = child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 123)]
            ),
            ("search", MINT): results[failure],
        },
    )
    assert wallet_holdings.main([OWNER, "--json"]) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert output.err == ""
    assert "secret" not in output.out
    assert report["status"] == "partial"
    wallet = report["wallets"][0]
    assert wallet["status"] == "success"
    assert wallet["inventory_complete"] is True
    assert wallet["holdings"][0]["raw_amount"] == "123"
    assert wallet["holdings"][0]["metadata"]["status"] == (
        "no_data" if failure == "empty" else "failed"
    )
    assert process.call_count == 2


@pytest.mark.parametrize(
    "change",
    ["query", "source", "chain", "mint", "duplicate", "metric_source"],
)
def test_search_receipts_reject_wrong_identity_or_provenance(
    monkeypatch, change
):
    document = search_document([MINT], [jupiter_token()])
    record = document["records"][0]
    if change in {"query", "source"}:
        document["request"]["options"][change] = "unexpected"
    elif change in {"mint", "chain"}:
        record["identity"][change] = OTHER_MINT
    elif change == "duplicate":
        document["records"].append(deepcopy(record))
    else:
        record["metrics"]["jupiter"]["source"] = "rpc"
    child_commands(monkeypatch, {("search", MINT): document})
    runner = GrowrRunner(30, 1)
    assert runner.search([MINT]) is None
    assert runner.scans[0]["error"] == "invalid_growr_output"


def test_real_subprocess_metadata_workflow(monkeypatch, tmp_path, capsys):
    (tmp_path / "wallet.json").write_text(
        json.dumps(wallet_document(entries=[account(10, MINT, 123)]))
    )
    (tmp_path / "search.json").write_text(
        json.dumps(
            search_document(
                [MINT], [jupiter_token(name="Name\x1b[2J\nfrom Jupiter")]
            )
        )
    )
    (tmp_path / "growr.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:3] == ['--json', '--no-color']\n"
        "path = Path(__file__).parent / ('%s.json' % sys.argv[3])\n"
        "print(path.read_text())\n"
        "print('secret', file=sys.stderr)\n"
    )
    monkeypatch.setattr("scripts.playbooks.runner.PROJECT_ROOT", tmp_path)
    assert wallet_holdings.main([OWNER]) == 0
    output = capsys.readouterr()
    assert "1.23 tokens" in output.out
    assert "amount source: jupiter" in output.out
    assert "Name[2Jfrom Jupiter" in output.out
    assert "https://project.example" in output.out
    assert "\x1b" not in output.out
    assert "secret" not in output.out
    assert output.err == ""


def test_missing_key_is_a_safe_real_growr_child_failure(monkeypatch):
    # An empty inherited value overrides any local dotenv key.
    monkeypatch.setenv("JUPITER_API_KEY", "")
    runner = GrowrRunner(10, 1)
    assert runner.search([MINT]) is None
    assert runner.scans[0]["returncode"] == 1
    assert runner.scans[0]["error"] == "growr_failed"


@pytest.mark.parametrize("limit", ["0", "11", "-1"])
def test_invalid_batch_limits_fail_before_subprocess(monkeypatch, limit):
    process = child_commands(monkeypatch, {})
    with pytest.raises(SystemExit) as error:
        wallet_holdings.main([OWNER, "--jupiter-batch-limit", limit])
    assert error.value.code == 2
    process.assert_not_called()


@pytest.mark.parametrize("mints", [[], [MINT] * 101, [MINT] * 2, ["JUP"]])
def test_runner_rejects_invalid_mint_batches_before_subprocess(
    monkeypatch, mints
):
    process = child_commands(monkeypatch, {})
    with pytest.raises(ValueError, match="Invalid Jupiter mint batch"):
        GrowrRunner(10, 1).search(mints)
    process.assert_not_called()
