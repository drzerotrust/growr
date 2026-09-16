"""Preserve usable evidence and reject invalid holder accounts."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

from growr_cli.integrations.http import HttpClient
from growr_cli.requests import RequestBudget
from growr_cli.scanners import TokenAccountScanner, WalletScanner
from growr_cli.solana.holders import validated_owner
from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID
from tests.conftest import make_token_account_bytes
from tests.test_history import SIGNATURE, transaction_body
from tests.test_machine import output_for
from tests.test_wallet_inventory import WALLET, holdings, inventory_rpc


@pytest.mark.parametrize("failed_read", ["get_balance_sol", "get_signatures"])
def test_wallet_context_failure_preserves_inventory(failed_read):
    rows = holdings()
    rpc = inventory_rpc(rows[:1], [])
    getattr(rpc, failed_read).side_effect = RuntimeError(
        "private provider message"
    )
    report = WalletScanner(rpc, "test").scan(str(WALLET))
    document = output_for(report, "wallet", str(WALLET))
    assert document["status"] == "partial"
    facts = document["records"][0]["facts"]
    assert len(facts["token_accounts"]["entries"]) == 1
    key = (
        "sol_balance"
        if failed_read == "get_balance_sol"
        else "recent_signatures"
    )
    assert facts[key] is None
    assert "private provider message" not in str(document)
    assert all(
        finding.label != "No recent signatures" for finding in report.findings
    )


def test_token_account_keeps_facts_when_owner_context_fails():
    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_account_data.return_value = (
        make_token_account_bytes(),
        str(SPL_TOKEN_PROGRAM_ID),
    )
    rpc.get_balance_sol.side_effect = RuntimeError("private")
    rpc.get_signatures.side_effect = RuntimeError("private")
    report = TokenAccountScanner(rpc, "test").scan(str(WALLET))
    document = output_for(report, "token-account", str(WALLET))
    assert document["status"] == "partial"
    facts = document["records"][0]["facts"]
    assert facts["token_account"]["raw_amount"] == "50"
    assert facts["owner_wallet"]["recent_signature_count"] is None


@pytest.mark.parametrize(
    "corruption",
    [
        None,
        "short",
        "program",
        "mint",
        "executable",
        "uninitialized",
        "other_token_program",
    ],
)
def test_holder_owner_requires_exact_valid_account(corruption):
    mint = Pubkey.from_bytes(bytes(range(32)))
    account = Mock(
        data=make_token_account_bytes(),
        owner=SPL_TOKEN_PROGRAM_ID,
        executable=False,
    )
    if corruption == "short":
        account.data = account.data[:64]
    elif corruption == "program":
        account.owner = Pubkey.default()
    elif corruption == "mint":
        account.data = bytes(32) + account.data[32:]
    elif corruption == "executable":
        account.executable = True
    elif corruption == "uninitialized":
        account.data = make_token_account_bytes(state=0)
    elif corruption == "other_token_program":
        account.owner = TOKEN_2022_PROGRAM_ID
    rpc = Mock()
    rpc.extract_bytes.side_effect = lambda data: data
    owner = validated_owner(rpc, account, mint, SPL_TOKEN_PROGRAM_ID)
    expected = str(Pubkey.from_bytes(bytes(range(32, 64))))
    assert owner == (expected if corruption is None else None)


def test_caught_cpi_does_not_claim_completed_inner_transfer():
    from growr_cli.analysis.transactions import normalize_transaction

    body = transaction_body()
    body["meta"]["innerInstructions"] = [
        {
            "index": 0,
            "instructions": deepcopy(
                body["transaction"]["message"]["instructions"]
            ),
        }
    ]
    body["meta"]["logMessages"] = [
        "Program 11111111111111111111111111111111 failed: insufficient funds"
    ]
    evidence = normalize_transaction(body, SIGNATURE)
    assert evidence["execution_status"] == "success"
    assert evidence["recording"]["inner_execution"] is False
    assert len(evidence["instructions"]) == 2
    assert all(row["inner_index"] is None for row in evidence["events"])


def test_http_budget_counts_failures_and_prevents_redirects():
    budget = RequestBudget(http_limit=1)
    client = HttpClient(1, budget)
    client.session.get = Mock(return_value=Mock(ok=True, status_code=302))
    try:
        assert client.get_json("https://example.invalid")[1] == "HTTP 302"
        assert (
            client.get_json("https://example.invalid")[1]
            == "Provider HTTP request budget exhausted"
        )
        assert client.session.get.call_count == 1
        assert client.session.get.call_args.kwargs["allow_redirects"] is False
        assert budget.snapshot()["http"] == {
            "attempted": 1,
            "failed": 1,
            "blocked": 1,
            "limit": 1,
        }
    finally:
        client.close()
