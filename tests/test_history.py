"""Transaction evidence, bounded history and RPC accounting tests."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey
from solders.rpc.responses import GetTransactionResp

import growr
from growr_cli.analysis.transactions import normalize_transaction
from growr_cli.requests import RequestBudget, RequestLimitError
from growr_cli.scanners.history import HistoryScanner
from growr_cli.solana.rpc import RpcError, SolanaRpcClient
from tests.conftest import make_signature_record
from tests.test_machine import output_for, validate

ADDRESS = "So11111111111111111111111111111111111111112"
OTHER = "11111111111111111111111111111111"
SIGNATURE = str(make_signature_record().signature)


def transaction_body(signature=SIGNATURE, *, failed=False):
    return {
        "slot": 42,
        "blockTime": 1700000000,
        "version": 0,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {
                        "pubkey": ADDRESS,
                        "signer": True,
                        "writable": True,
                        "source": "transaction",
                    },
                    {
                        "pubkey": OTHER,
                        "signer": False,
                        "writable": True,
                        "source": "lookupTable",
                    },
                ],
                "recentBlockhash": OTHER,
                "instructions": [
                    {
                        "program": "system",
                        "programId": OTHER,
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": ADDRESS,
                                "destination": OTHER,
                                "lamports": 123,
                            },
                        },
                        "stackHeight": 1,
                    }
                ],
            },
        },
        "meta": {
            "status": {"Err": "InvalidArgument"} if failed else {"Ok": None},
            "err": {"InstructionError": [0, "InvalidArgument"]}
            if failed
            else None,
            "fee": 5000,
            "preBalances": [10000, 1000],
            "postBalances": [5000, 1000] if failed else [4877, 1123],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "innerInstructions": [],
            "logMessages": [],
        },
    }


def test_failed_transaction_keeps_fee_and_deltas_without_completed_events():
    evidence = normalize_transaction(transaction_body(failed=True), SIGNATURE)
    assert evidence["execution_status"] == "failed"
    assert evidence["fee_lamports"] == "5000"
    assert evidence["native_balances"][0]["delta_lamports"] == "-5000"
    assert evidence["events"] == []
    assert evidence["instructions"][0]["type"] == "transfer"


def test_parsed_lookup_keys_and_inner_positions_are_preserved():
    body = transaction_body()
    body["meta"]["loadedAddresses"] = {"writable": [OTHER], "readonly": []}
    body["meta"]["innerInstructions"] = [
        {
            "index": 0,
            "instructions": deepcopy(
                body["transaction"]["message"]["instructions"]
            ),
        }
    ]
    evidence = normalize_transaction(body, SIGNATURE)
    assert evidence["account_keys"] == [ADDRESS, OTHER]
    assert evidence["events"][1]["inner_index"] == 0
    assert evidence["events"][1]["outer_index"] == 0
    assert evidence["events"][1]["raw_amount"] == "123"
    assert evidence["events"][1]["signature"] == SIGNATURE


def test_raw_lookup_keys_resolve_instruction_program_indices():
    body = transaction_body()
    message = body["transaction"]["message"]
    message["accountKeys"] = [ADDRESS]
    message["header"] = {"numRequiredSignatures": 1}
    message["instructions"] = [
        {"programIdIndex": 1, "accounts": [0], "data": "abc"}
    ]
    body["meta"]["loadedAddresses"] = {"writable": [OTHER], "readonly": []}
    evidence = normalize_transaction(body, SIGNATURE)
    assert evidence["instructions"][0]["program_id"] == OTHER
    assert evidence["instructions"][0]["type"] == "unknown"
    assert evidence["events"] == []


def test_missing_token_balance_side_is_unknown_not_zero():
    body = transaction_body()
    body["meta"]["preTokenBalances"] = [
        {
            "accountIndex": 1,
            "mint": ADDRESS,
            "uiTokenAmount": {"amount": "18446744073709551615", "decimals": 9},
        }
    ]
    evidence = normalize_transaction(body, SIGNATURE)
    token = evidence["token_balances"][0]
    assert token["before"]["raw_amount"] == "18446744073709551615"
    assert token["before"]["owner"] is None
    assert token["after"] is None
    assert token["delta_raw"] is None


@pytest.mark.parametrize(
    "action", ["transferChecked", "mintTo", "burn", "closeAccount"]
)
def test_token_actions_preserve_raw_units_and_program_identity(action):
    body = transaction_body()
    program = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    info = {
        "mint": ADDRESS,
        "account": OTHER,
        "mintAuthority": ADDRESS,
        "amount": "18446744073709551615",
    }
    if action == "transferChecked":
        info["tokenAmount"] = {"amount": "18446744073709551615", "decimals": 9}
    body["transaction"]["message"]["instructions"] = [
        {
            "programId": program,
            "parsed": {"type": action, "info": info},
        }
    ]
    event = normalize_transaction(body, SIGNATURE)["events"][0]
    assert event["program_id"] == program
    assert event["type"] == action
    assert event["raw_amount"] == "18446744073709551615"
    assert event["authority"] == ADDRESS


def test_history_transport_sends_explicit_commitment_and_cursors():
    import httpx

    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": []}
        )

    rpc = SolanaRpcClient("https://example.invalid", 1, commitment="confirmed")
    rpc.client._provider.session.close()
    rpc.client._provider.session = httpx.Client(
        transport=httpx.MockTransport(respond)
    )
    try:
        assert (
            rpc.get_signatures(
                Pubkey.from_string(ADDRESS), 10, before=SIGNATURE
            )
            == []
        )
        assert requests[0]["method"] == "getSignaturesForAddress"
        config = requests[0]["params"][1]
        assert config["commitment"] == "confirmed"
        assert config["before"] == SIGNATURE
        assert config["limit"] == 10
    finally:
        rpc.close()


@pytest.mark.parametrize(
    "failure", ["missing", "unsupported", "mismatched", "rpc"]
)
def test_missing_and_invalid_bodies_preserve_signature_coverage(failure):
    rpc = Mock()
    body = transaction_body()
    if failure == "unsupported":
        body["version"] = 1
    if failure == "mismatched":
        body["transaction"]["signatures"] = [
            str(make_signature_record(2).signature)
        ]
    rpc.get_transaction.return_value = None if failure == "missing" else body
    if failure == "rpc":
        rpc.get_transaction.side_effect = RpcError("failed")
    report = HistoryScanner(rpc, "test").transaction(SIGNATURE)
    document = output_for(report, "transaction", SIGNATURE)
    assert document["status"] == "partial"
    assert document["records"][0]["facts"]["available"] is False
    assert document["records"][0]["identity"]["signature"] == SIGNATURE


def test_history_deduplicates_details_and_uses_last_returned_cursor():
    rpc = Mock()
    rpc.get_signatures.return_value = [
        make_signature_record(),
        make_signature_record(2),
        make_signature_record(),
    ]
    rpc.get_transaction.side_effect = lambda signature: transaction_body(
        signature
    )
    report = HistoryScanner(rpc, "test").history(
        ADDRESS, limit=3, details=True
    )
    document = output_for(
        report, "history", ADDRESS, "--limit", "3", "--details"
    )
    assert len(document["records"][0]["facts"]["entries"]) == 2
    assert rpc.get_transaction.call_count == 2
    assert document["pagination"]["next_before"] == SIGNATURE
    assert document["pagination"]["complete_history"] is False


def test_empty_history_does_not_fetch_bodies():
    rpc = Mock()
    rpc.get_signatures.return_value = []
    report = HistoryScanner(rpc, "test").history(ADDRESS, details=True)
    assert report.summary["entries"] == []
    assert report.summary["pagination"]["provider_page_exhausted"] is True
    rpc.get_transaction.assert_not_called()


def test_rpc_budget_atomic_and_failed_attempts_count():
    budget = RequestBudget(rpc_limit=3)

    def reserve(_):
        try:
            row = budget.start("rpc", "getBalance")
        except RequestLimitError:
            return
        budget.finish(row, "failed")

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(reserve, range(10)))
    assert budget.snapshot()["rpc"] == {
        "attempted": 3,
        "failed": 3,
        "blocked": 7,
        "limit": 3,
    }


def test_sdk_translation_records_transaction_slot_and_version_cap():
    rpc = SolanaRpcClient("https://example.invalid", 1)
    response = GetTransactionResp.from_json(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": transaction_body()})
    )
    rpc.client.get_transaction = Mock(return_value=response)
    try:
        body = rpc.get_transaction(SIGNATURE)
        assert (
            normalize_transaction(body, SIGNATURE)["events"][0]["raw_amount"]
            == "123"
        )
        assert (
            rpc.client.get_transaction.call_args.kwargs[
                "max_supported_transaction_version"
            ]
            == 0
        )
        assert rpc.budget.snapshot()["observations"][0]["slot"] == 42
    finally:
        rpc.close()


def test_wallet_retains_exact_lamports_and_slots(monkeypatch, capsys):
    def factory(*args, **kwargs):
        rpc = SolanaRpcClient(*args, **kwargs)
        rpc.client.get_balance = Mock(
            return_value=SimpleNamespace(
                value=18446744073709551615, context=SimpleNamespace(slot=90)
            )
        )
        rpc.client.get_signatures_for_address = Mock(
            return_value=SimpleNamespace(value=[make_signature_record()])
        )
        rpc.client.get_token_accounts_by_owner = Mock(
            return_value=SimpleNamespace(
                value=[], context=SimpleNamespace(slot=91)
            )
        )
        return rpc

    monkeypatch.setattr(growr, "SolanaRpcClient", factory)
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", "wallet", ADDRESS])
    assert growr.main() == 0
    output = capsys.readouterr()
    document = validate(json.loads(output.out))
    assert output.err == ""
    assert (
        document["records"][0]["facts"]["sol_lamports"]
        == "18446744073709551615"
    )
    assert (
        document["records"][0]["facts"]["recent_signatures"][0]["signature"]
        == SIGNATURE
    )
    assert document["run"]["requests"]["rpc"]["attempted"] == 4
    assert {
        item["commitment"]
        for item in document["run"]["requests"]["observations"]
    } == {"finalized"}


@pytest.mark.parametrize(
    "command",
    [
        ["transaction", "invalid"],
        ["history", ADDRESS, "--limit", "101"],
        ["history", ADDRESS, "--before", "invalid"],
    ],
)
def test_invalid_history_arguments_fail_before_clients(
    monkeypatch, capsys, command
):
    client = Mock()
    monkeypatch.setattr(growr, "SolanaRpcClient", client)
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", *command])
    assert growr.main() == 2
    document = validate(json.loads(capsys.readouterr().out))
    assert document["error"]["code"] == "INVALID_ARGUMENTS"
    client.assert_not_called()


def test_rpc_limit_blocks_before_transport_and_retains_observation():
    rpc = SolanaRpcClient(
        "https://example.invalid", 1, budget=RequestBudget(rpc_limit=1)
    )
    rpc.client.get_balance = Mock(side_effect=RuntimeError("secret"))
    try:
        with pytest.raises(RpcError):
            rpc.get_balance_sol(Pubkey.from_string(ADDRESS))
        with pytest.raises(RpcError, match="budget exhausted"):
            rpc.get_balance_sol(Pubkey.from_string(ADDRESS))
        assert rpc.client.get_balance.call_count == 1
        assert rpc.budget.snapshot()["rpc"]["failed"] == 1
        assert "secret" not in json.dumps(rpc.budget.snapshot())
    finally:
        rpc.close()
