"""Release regression checks for defects reproduced during review.

These preserve the required behavior for each reproduced review finding.
"""

import json
from unittest.mock import Mock

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from solders.pubkey import Pubkey

import growr
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import report_summary
from growr_cli.machine.schema import response_schema
from growr_cli.models import ScanReport
from growr_cli.renderers.scans import TokenConsoleRenderer
from growr_cli.solana.rpc import (
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    RpcError,
    format_rpc_error,
)
from tests.conftest import make_mint_bytes
from tests.test_enrichment import MINT
from tests.test_machine import STAMP


def wallet_rpc():
    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_balance_sol.return_value = 1.0
    rpc.get_signatures.return_value = []
    rpc.get_token_accounts_by_owner.return_value = []
    return rpc


@pytest.mark.parametrize("account_kind", ["multisig", "extended_mint"])
def test_token_account_command_rejects_other_account_types(
    monkeypatch, capsys, account_kind
):
    if account_kind == "multisig":
        # A one-of-one SPL multisig: m, n, initialized, 11 signers.
        data = b"\x01\x01\x01" + bytes(Pubkey.from_string(MINT)) + bytes(320)
        owner = SPL_TOKEN_PROGRAM_ID
    else:
        # Extended mints have padding to byte 165, then type 1 (mint).
        data = make_mint_bytes() + bytes(83) + b"\x01" + bytes(4)
        owner = TOKEN_2022_PROGRAM_ID
    rpc = wallet_rpc()
    rpc.get_account_data.return_value = (data, str(owner))
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", "token-account", MINT]
    )

    exit_code = growr.main()
    document = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert document["status"] == "error"
    assert document["records"] == []
    rpc.get_balance_sol.assert_not_called()


@pytest.mark.parametrize("key_name", ["token", "api_key", "access_token"])
def test_rpc_http_errors_redact_other_credential_names(key_name):
    secret = "synthetic-review-secret"
    request = httpx.Request("POST", "https://rpc.example")
    response = httpx.Response(
        403,
        request=request,
        text="Access denied: %s=%s" % (key_name, secret),
    )
    error = httpx.HTTPStatusError(
        "forbidden", request=request, response=response
    )
    assert secret not in format_rpc_error(error, "getBalance")


def test_rpc_override_stays_hidden_in_partial_wallet_json(monkeypatch, capsys):
    secret = "synthetic-path-credential"
    endpoint = "https://rpc.example/%s" % secret
    request = httpx.Request("POST", endpoint)
    response = httpx.Response(
        403, request=request, text="Forbidden request to %s" % endpoint
    )
    error = httpx.HTTPStatusError(
        "forbidden", request=request, response=response
    )
    rpc = wallet_rpc()
    rpc.get_token_accounts_by_owner.side_effect = RpcError(
        format_rpc_error(error, "getTokenAccountsByOwner")
    )
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(
        "sys.argv",
        ["growr.py", "--rpc-url", endpoint, "--json", "wallet", MINT],
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "partial"
    assert secret not in output.out + output.err


def test_token_console_neutralizes_untrusted_metadata(capsys):
    report = ScanReport("token", MINT, "test RPC", STAMP)
    report.summary["metadata"] = {
        "name": "\x1b[2JForged summary",
        "symbol": "\x1b]52;c;c3ludGhldGlj\x07",
    }
    TokenConsoleRenderer(use_color=False).render(report)
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\x07" not in output


def test_malformed_single_token_responses_are_failed_coverage():
    http = Mock(
        get_json=Mock(return_value=({"error": "service unavailable"}, None))
    )
    result = JupiterClient(http, "synthetic-key").get_token(MINT)
    assert result.status == "failed"


def test_discovery_social_links_produce_schema_valid_json(monkeypatch, capsys):
    monkeypatch.setattr(
        growr.settings, "JUPITER_API_KEY", "synthetic-review-key"
    )
    tokens = [
        {
            "id": MINT,
            "website": "https://project.example/a b",
            "twitter": "https://x.com/project",
        }
    ]
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(return_value=Mock(ok=True, json=Mock(return_value=tokens))),
    )
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", "list", "jupiter"])
    assert growr.main() == 0
    document = json.loads(capsys.readouterr().out)
    assert document["records"][0]["social"]["score"] == 40
    for link in document["records"][0]["social"]["links"]:
        assert not any(character.isspace() for character in link["url"])
    Draft202012Validator(
        response_schema(), format_checker=FormatChecker()
    ).validate(document)


@pytest.mark.parametrize(
    ("format_name", "invalid"),
    [("uri", "https://project.example/a b"), ("date-time", "not-a-timestamp")],
)
def test_declared_json_formats_are_actually_checked(format_name, invalid):
    assert not FormatChecker().conforms(invalid, format_name)


def test_rugcheck_zero_score_is_preserved():
    assert report_summary({"score": 0})["score"] == 0
