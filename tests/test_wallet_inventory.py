"""Wallet inventory addresses, exact quantities and partial coverage."""

import json
from unittest.mock import Mock, call

import pytest
from jsonschema import ValidationError
from solders.account import Account
from solders.pubkey import Pubkey
from solders.rpc.responses import RpcKeyedAccount

import growr
from growr_cli.scanners.wallet import WalletScanner
from growr_cli.solana.inventory import token_account_entries
from growr_cli.solana.rpc import (
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    RpcError,
)
from tests.conftest import make_rpc_token_account, make_signature_record
from tests.test_machine import output_for, validate

WALLET = Pubkey.from_string("Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit")
FIRST = Pubkey.from_bytes(bytes([1]) * 32)
SECOND = Pubkey.from_bytes(bytes([2]) * 32)


def holdings():
    return [
        make_rpc_token_account(FIRST, WALLET, SPL_TOKEN_PROGRAM_ID, amount=0),
        make_rpc_token_account(
            SECOND,
            WALLET,
            TOKEN_2022_PROGRAM_ID,
            amount=2**64 - 1,
            state=2,
            extended=True,
        ),
    ]


def inventory_rpc(spl, token_2022):
    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_balance_sol.return_value = 1.0
    rpc.get_signatures.return_value = [make_signature_record()]

    def accounts(wallet, program):
        assert wallet == WALLET
        result = spl if program == SPL_TOKEN_PROGRAM_ID else token_2022
        if isinstance(result, Exception):
            raise result
        return result

    rpc.get_token_accounts_by_owner.side_effect = accounts
    return rpc


def inventory_document(rpc):
    report = WalletScanner(rpc, "test RPC").scan(str(WALLET))
    return output_for(report, "wallet", str(WALLET))


@pytest.mark.parametrize("json_mode", [False, True])
def test_wallet_cli_exposes_both_programs_without_extra_rpc(
    monkeypatch, capsys, json_mode
):
    spl, token_2022 = holdings()
    rpc = inventory_rpc([spl], [token_2022])
    http = Mock()
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(growr, "HttpClient", Mock(return_value=http))
    flags = ["--json", "--include-raw"] if json_mode else ["--no-color"]
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "wallet", str(WALLET)]
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    if json_mode:
        document = validate(json.loads(output.out))
        assert document["status"] == "success"
        record = document["records"][0]
        assert record["facts"]["source"] == "rpc"
        assert record["raw"] == {}
        inventory = record["facts"]["token_accounts"]
        assert inventory["total_account_count"] == 2
        assert inventory["unparsed_account_count"] == 0
        assert inventory["entries"] == [
            {
                "address": str(FIRST),
                "mint": str(Pubkey.from_bytes(spl.account.data[:32])),
                "token_program": "spl_token",
                "raw_amount": "0",
                "state": "initialized",
            },
            {
                "address": str(SECOND),
                "mint": str(Pubkey.from_bytes(token_2022.account.data[:32])),
                "token_program": "token_2022",
                "raw_amount": "18446744073709551615",
                "state": "frozen",
            },
        ]
    else:
        assert "Token accounts (validated holdings)" in output.out
        assert str(FIRST) in output.out and str(SECOND) in output.out
        assert "18446744073709551615" in output.out
        assert "token-account <ADDRESS>" in output.out
    rpc.get_balance_sol.assert_called_once_with(WALLET)
    rpc.get_signatures.assert_called_once_with(WALLET, 10)
    rpc.get_token_accounts_by_owner.assert_has_calls(
        [
            call(WALLET, SPL_TOKEN_PROGRAM_ID),
            call(WALLET, TOKEN_2022_PROGRAM_ID),
        ],
        any_order=True,
    )
    assert rpc.get_token_accounts_by_owner.call_count == 2
    rpc.get_account_data.assert_not_called()
    rpc.get_multiple_accounts.assert_not_called()
    http.get_json.assert_not_called()
    rpc.close.assert_called_once()
    http.close.assert_called_once()


@pytest.mark.parametrize("failed", ["spl_token", "token_2022", "both", None])
def test_failed_programs_keep_other_entries_and_distinguish_empty(failed):
    spl, token_2022 = holdings()
    error = RpcError("getTokenAccountsByOwner failed via RPC")
    spl_rows = error if failed in {"spl_token", "both"} else [spl]
    new_rows = error if failed in {"token_2022", "both"} else [token_2022]
    if failed is None:
        spl_rows, new_rows = [], []
    document = inventory_document(inventory_rpc(spl_rows, new_rows))
    inventory = document["records"][0]["facts"]["token_accounts"]
    assert document["status"] == ("partial" if failed else "success")
    assert inventory["unparsed_account_count"] == 0
    if failed in {None, "both"}:
        assert inventory["entries"] == []
        assert inventory["total_account_count"] == (None if failed else 0)
    else:
        assert inventory["%s_account_count" % failed] is None
        expected = SECOND if failed == "spl_token" else FIRST
        assert inventory["entries"][0]["address"] == str(expected)
        assert inventory["total_account_count"] == 1
    operations = {item["operation"] for item in document["coverage"]}
    for program in ("spl_token", "token_2022"):
        assert ("%s_inventory" % program in operations) == (
            failed in {program, "both"}
        )


@pytest.mark.parametrize(
    "problem",
    ["short", "owner", "program", "executable", "mint", "duplicate", "shape"],
)
def test_invalid_rows_preserve_other_holdings_with_partial_coverage(problem):
    spl, token_2022 = holdings()
    account = spl.account
    data = account.data
    owner = account.owner
    executable = False
    if problem == "short":
        data = b""
    elif problem == "owner":
        data = data[:32] + bytes(32) + data[64:]
    elif problem == "program":
        owner = TOKEN_2022_PROGRAM_ID
    elif problem == "executable":
        executable = True
    elif problem == "mint":
        # Token-2022 mint discriminator in a token-account response.
        data = data + b"\x01" + bytes(4)
        owner = TOKEN_2022_PROGRAM_ID
    bad = RpcKeyedAccount(SECOND, Account(1, data, owner, executable))
    if problem == "duplicate":
        bad = spl
    elif problem == "shape":
        bad = object()
    rpc = (
        inventory_rpc([spl], [token_2022, bad])
        if problem == "mint"
        else inventory_rpc([spl, bad], [token_2022])
    )
    document = inventory_document(rpc)
    inventory = document["records"][0]["facts"]["token_accounts"]
    assert document["status"] == "partial"
    assert inventory["total_account_count"] == 3
    assert inventory["unparsed_account_count"] == 1
    assert [row["address"] for row in inventory["entries"]] == [
        str(FIRST),
        str(SECOND),
    ]
    assert any(
        item["operation"] == "wallet_inventory_decode"
        and item["status"] == "partial"
        for item in document["coverage"]
    )


def test_token_2022_base_and_extended_accounts_keep_return_order():
    accounts = [
        make_rpc_token_account(
            address, WALLET, TOKEN_2022_PROGRAM_ID, extended=extended
        )
        for address, extended in ((SECOND, False), (FIRST, True))
    ]
    entries, rejected = token_account_entries(
        accounts, WALLET, TOKEN_2022_PROGRAM_ID
    )
    assert rejected == 0
    assert [entry["address"] for entry in entries] == [str(SECOND), str(FIRST)]


def test_inventory_schema_rejects_numeric_raw_balance():
    spl, token_2022 = holdings()
    document = inventory_document(inventory_rpc([spl], [token_2022]))
    inventory = document["records"][0]["facts"]["token_accounts"]
    inventory["entries"][0]["raw_amount"] = 1.5
    with pytest.raises(ValidationError):
        validate(document)
