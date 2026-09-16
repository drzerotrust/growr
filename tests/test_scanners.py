import json
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey
from solders.rpc.responses import GetTokenLargestAccountsResp

from growr_cli.decoding import parse_mint
from growr_cli.models import ScanReport
from growr_cli.scanners import (
    TokenAccountScanner,
    TokenScanner,
    WalletScanner,
)
from growr_cli.solana_rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID
from tests.conftest import (
    make_mint_bytes,
    make_rpc_token_account,
    make_token_account_bytes,
)

MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_token_scan_rejects_non_token_program_owner() -> None:
    rpc = Mock()
    rpc.parse_address.return_value = Pubkey.from_string(MINT)
    rpc.get_account_data.return_value = (
        make_mint_bytes(),
        "11111111111111111111111111111111",
    )
    scanner = TokenScanner(rpc, "test RPC", Mock())

    with pytest.raises(ValueError, match="not an SPL mint"):
        scanner.scan(MINT, include_jupiter=False, include_rugcheck=False)


def test_token_account_scan_rejects_non_token_program_owner() -> None:
    rpc = Mock()
    rpc.parse_address.return_value = Pubkey.from_string(MINT)
    rpc.get_account_data.return_value = (
        make_token_account_bytes(),
        "11111111111111111111111111111111",
    )
    scanner = TokenAccountScanner(rpc, "test RPC")

    with pytest.raises(ValueError, match="not an SPL token account"):
        scanner.scan(MINT)


def test_uninitialized_mint_does_not_emit_authority_findings() -> None:
    scanner = TokenScanner(Mock(), "test RPC", Mock())
    report = ScanReport("token", MINT, "test RPC", "now")
    mint = parse_mint(
        make_mint_bytes(initialized=False, has_mint_authority=True),
        str(SPL_TOKEN_PROGRAM_ID),
    )

    scanner._add_mint_findings(report, mint)

    labels = [finding.label for finding in report.findings]
    assert labels == ["Mint account uninitialized"]
    assert all(
        finding.label != "Mint authority enabled"
        for finding in report.findings
    )


def test_initialized_mint_emits_authority_findings() -> None:
    scanner = TokenScanner(Mock(), "test RPC", Mock())
    report = ScanReport("token", MINT, "test RPC", "now")
    mint = parse_mint(
        make_mint_bytes(
            initialized=True,
            has_mint_authority=True,
            has_freeze_authority=True,
        ),
        str(SPL_TOKEN_PROGRAM_ID),
    )

    scanner._add_mint_findings(report, mint)

    labels = [finding.label for finding in report.findings]
    assert "Mint authority enabled" in labels
    assert "Freeze authority enabled" in labels


def test_wallet_scan_isolates_per_program_errors() -> None:
    rpc = Mock()
    wallet = Pubkey.from_string("11111111111111111111111111111111")
    rpc.parse_address.return_value = wallet
    rpc.get_balance_sol.return_value = 1.5
    rpc.get_signatures.return_value = ["sig"]

    def fake_get_token_accounts(_wallet, program_id):
        if program_id == SPL_TOKEN_PROGRAM_ID:
            raise RuntimeError("spl down")
        if program_id == TOKEN_2022_PROGRAM_ID:
            return [
                make_rpc_token_account(
                    Pubkey.from_bytes(bytes([number]) * 32),
                    wallet,
                    program_id,
                    extended=True,
                )
                for number in (1, 2)
            ]
        raise AssertionError("unexpected program %s" % program_id)

    rpc.get_token_accounts_by_owner.side_effect = fake_get_token_accounts
    scanner = WalletScanner(rpc, "test RPC")

    report = scanner.scan(str(wallet))

    assert report.summary["token_accounts"]["spl_token_account_count"] is None
    assert report.summary["token_accounts"]["token_2022_account_count"] == 2
    assert report.summary["token_accounts"]["total_account_count"] == 2
    assert len(report.summary["token_accounts"]["entries"]) == 2
    assert report.summary["token_accounts"]["unparsed_account_count"] == 0
    assert any(
        finding.label == "SPL token inventory incomplete"
        for finding in report.findings
    )
    assert all(
        finding.label != "Token-2022 inventory incomplete"
        for finding in report.findings
    )


def test_token_scan_can_skip_all_market_providers() -> None:
    rpc, providers = Mock(), Mock()
    rpc.parse_address.return_value = Pubkey.from_string(MINT)
    rpc.get_account_data.side_effect = [
        (make_mint_bytes(), str(SPL_TOKEN_PROGRAM_ID)),
        (None, None),
    ]
    rpc.get_largest_token_accounts.return_value = []
    rpc.get_multiple_accounts.return_value = []
    scanner = TokenScanner(rpc, "test RPC", providers)

    report = scanner.scan(
        MINT,
        include_jupiter=False,
        include_rugcheck=False,
        include_market_context=False,
    )

    assert report.summary["mint"]["supply"] == "1000"
    assert report.summary["holders"]["top_accounts"] == []
    assert report.providers == []
    assert not providers.mock_calls


def test_largest_accounts_decode_sdk_nested_amount_and_resolve_owners() -> (
    None
):
    response = GetTokenLargestAccountsResp.from_json(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "context": {"slot": 1},
                    "value": [
                        {
                            "address": MINT,
                            "amount": "900",
                            "decimals": 6,
                            "uiAmount": 0.0009,
                            "uiAmountString": "0.0009",
                        }
                    ],
                },
            }
        )
    )
    rpc = Mock()
    rpc.get_largest_token_accounts.return_value = response.value
    rpc.get_multiple_accounts.return_value = [
        Mock(
            data=bytes(Pubkey.from_string(MINT))
            + make_token_account_bytes()[32:],
            owner=SPL_TOKEN_PROGRAM_ID,
            executable=False,
        )
    ]
    rpc.extract_bytes.side_effect = lambda data: data
    scanner = TokenScanner(rpc, "test RPC", Mock())

    holders = scanner._read_holders(Pubkey.from_string(MINT), "1000", 6)

    assert holders["top_twenty_percent"] == 90
    assert holders["top_accounts"][0] == {
        "token_account": MINT,
        "owner": str(Pubkey.from_bytes(bytes(range(32, 64)))),
        "raw_amount": "900",
        "ui_amount": 0.0009,
        "amount_tokens": "0.0009",
        "percent_of_supply": 90,
    }
