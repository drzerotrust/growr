"""CLI coverage for token-program layouts and mistaken wallet inputs."""

import json
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

import growr
from growr_cli.solana.decoding import parse_mint, parse_token_account
from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID
from tests.conftest import make_token_account_bytes
from tests.test_machine import validate

WALLET = "Beqv6dzTcjV2eodo8RRXCiCcnSYrS1vkQKhfqwHXqeit"
SYSTEM_PROGRAM = "11111111111111111111111111111111"


def account_rpc(monkeypatch, data, owner, json_mode):
    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_account_data.return_value = (data, str(owner))
    rpc.get_balance_sol.return_value = 1.0
    rpc.get_signatures.return_value = []
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(growr, "HttpClient", Mock())
    flags = ["--json"] if json_mode else ["--no-color"]
    monkeypatch.setattr(
        "sys.argv", ["growr.py", *flags, "token-account", WALLET]
    )
    return rpc


@pytest.mark.parametrize("json_mode", [False, True])
def test_system_wallet_is_rejected_before_owner_context(
    monkeypatch, capsys, json_mode
):
    # Reproduce the reported address's live owner and empty data buffer.
    rpc = account_rpc(monkeypatch, b"", SYSTEM_PROGRAM, json_mode)
    assert growr.main() == 1
    output = capsys.readouterr()
    if json_mode:
        document = validate(json.loads(output.out))
        assert document["status"] == "error"
        assert document["records"] == []
        assert output.err == ""
    else:
        assert output.out == ""
        assert "System Program account" in output.err
        assert "growr.py wallet <ADDRESS>" in output.err
        assert "too short" not in output.err
    rpc.get_balance_sol.assert_not_called()
    rpc.get_signatures.assert_not_called()
    rpc.close.assert_called_once()


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    ("program", "suffix", "label"),
    [
        (SPL_TOKEN_PROGRAM_ID, b"", "spl_token"),
        (TOKEN_2022_PROGRAM_ID, b"", "token_2022"),
        # Account discriminator 2 followed by ImmutableOwner TLV (7, 0).
        (TOKEN_2022_PROGRAM_ID, b"\x02\x07\x00\x00\x00", "token_2022"),
    ],
)
def test_token_account_cli_accepts_both_programs(
    monkeypatch, capsys, json_mode, program, suffix, label
):
    data = make_token_account_bytes(amount=123, state=2) + suffix
    rpc = account_rpc(monkeypatch, data, program, json_mode)
    assert growr.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    if json_mode:
        document = validate(json.loads(output.out))
        assert document["status"] == "success"
        record = document["records"][0]
        assert record["kind"] == "token_account"
        account = record["facts"]["token_account"]
        assert account["token_program"] == label
        assert account["raw_amount"] == "123"
        assert account["state"] == "frozen"
        assert account["owner"] == str(Pubkey.from_bytes(data[32:64]))
    else:
        assert label in output.out
        assert "frozen" in output.out
    owner = Pubkey.from_bytes(data[32:64])
    rpc.get_balance_sol.assert_called_once_with(owner)
    rpc.get_signatures.assert_called_once_with(owner, 10)
    rpc.close.assert_called_once()


@pytest.mark.parametrize("decoder", [parse_mint, parse_token_account])
def test_empty_wallet_data_is_classified_by_owner(decoder):
    with pytest.raises(ValueError, match="System Program account"):
        decoder(b"", SYSTEM_PROGRAM)


@pytest.mark.parametrize(
    "program", [SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID]
)
@pytest.mark.parametrize("size", [0, 82, 164])
def test_short_token_program_data_still_fails(program, size):
    with pytest.raises(
        ValueError, match="expected at least 165 bytes, got %s" % size
    ):
        parse_token_account(bytes(size), str(program))
