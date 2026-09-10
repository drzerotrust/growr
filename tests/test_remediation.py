"""Positive controls and output-boundary checks for review fixes."""

import json
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from jsonschema import FormatChecker

import growr
from growr_cli import settings
from growr_cli.analysis.social import normalize_link, social_presence
from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import report_summary
from growr_cli.logger import get_logger
from growr_cli.machine.response import serialize
from growr_cli.models import Finding, ScanReport
from growr_cli.safety import redact_endpoint, safe_text
from growr_cli.solana.decoding import parse_mint, parse_token_account
from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID
from tests.conftest import make_mint_bytes, make_token_account_bytes
from tests.test_enrichment import MINT
from tests.test_machine import STAMP, validate


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("initialized", [False, True])
def test_token_2022_mints_keep_valid_base_and_extended_layouts(
    extended, initialized
):
    data = make_mint_bytes(initialized=initialized)
    if extended:
        data += bytes(83) + b"\x01" + bytes(4)
    result = parse_mint(data, str(TOKEN_2022_PROGRAM_ID))
    assert result["supply"] == "1000"
    assert result["initialized"] is initialized


@pytest.mark.parametrize("state", [0, 1, 2])
@pytest.mark.parametrize("extended", [False, True])
def test_token_2022_accounts_keep_states_and_amounts(state, extended):
    data = make_token_account_bytes(state=state, amount=123)
    if extended:
        data += b"\x02" + bytes(4)
    result = parse_token_account(data, str(TOKEN_2022_PROGRAM_ID))
    assert result["raw_amount"] == "123"
    assert result["state"] == ("uninitialized", "initialized", "frozen")[state]


@pytest.mark.parametrize("offset", [0, 45, 46])
def test_mint_rejects_invalid_flags_and_option_tags(offset):
    data = bytearray(make_mint_bytes())
    data[offset] = 2
    with pytest.raises(ValueError, match="Invalid SPL"):
        parse_mint(bytes(data), str(SPL_TOKEN_PROGRAM_ID))


@pytest.mark.parametrize("offset", [72, 108, 109, 129])
def test_token_account_rejects_invalid_states_and_option_tags(offset):
    data = bytearray(make_token_account_bytes())
    data[offset] = 3
    with pytest.raises(ValueError, match="Invalid SPL"):
        parse_token_account(bytes(data), str(SPL_TOKEN_PROGRAM_ID))


def test_wrong_type_and_nonzero_mint_padding_are_rejected():
    with pytest.raises(ValueError):
        parse_mint(make_token_account_bytes(), str(SPL_TOKEN_PROGRAM_ID))
    data = make_mint_bytes() + b"\x01" + bytes(82) + b"\x01"
    with pytest.raises(ValueError, match="padding"):
        parse_mint(data, str(TOKEN_2022_PROGRAM_ID))
    with pytest.raises(ValueError, match="account type"):
        parse_token_account(
            make_token_account_bytes() + b"\x01",
            str(TOKEN_2022_PROGRAM_ID),
        )


@pytest.mark.parametrize("payload", [[], [{"id": "different-mint"}]])
def test_valid_empty_jupiter_matches_remain_no_data(payload):
    http = Mock(get_json=Mock(return_value=(payload, None)))
    assert JupiterClient(http, "key").get_token(MINT).status == "no_data"


@pytest.mark.parametrize("payload", [{"pairs": []}, {"pairs": None}])
def test_valid_empty_dexscreener_responses_remain_no_data(payload):
    http = Mock(get_json=Mock(return_value=(payload, None)))
    assert DexscreenerClient(http).get_pairs(MINT).status == "no_data"


@pytest.mark.parametrize("payload", [None, {}, [None], ["invalid"]])
def test_bad_jupiter_records_fail_coverage(payload):
    http = Mock(get_json=Mock(return_value=(payload, None)))
    assert JupiterClient(http, "key").get_token(MINT).status == "failed"


@pytest.mark.parametrize("pairs", [[None], ["invalid"], {}, 12])
def test_bad_dexscreener_records_fail_coverage(pairs):
    http = Mock(get_json=Mock(return_value=({"pairs": pairs}, None)))
    assert DexscreenerClient(http).get_pairs(MINT).status == "failed"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://münich.example/café?q=été",
            "https://xn--mnich-kva.example/caf%C3%A9?q=%C3%A9t%C3%A9",
        ),
        ("http://[2001:db8::1]:8080/path", "http://[2001:db8::1]:8080/path"),
        (
            "https://project.example/a%20b?x=1&y=2",
            "https://project.example/a%20b?x=1&y=2",
        ),
    ],
)
def test_valid_links_preserve_uri_meaning(url, expected):
    result = normalize_link(
        {"url": url, "kind": "website", "source": "stonks"}
    )
    assert result["url"] == expected
    assert FormatChecker().conforms(result["url"], "uri")


@pytest.mark.parametrize(
    "url",
    [
        "https://project.example/a b",
        "https://project.example/?q=a b",
        "https://project.example/%zz",
        "https://project.example/%",
        "https://project.example:0/",
        "https://project.example:99999/",
        "https://-invalid.example/",
        "https://project.example/\x1b[2J",
        "https://stonkfun.xyz./project",
        "https://user:password@project.example",
    ],
)
def test_invalid_links_do_not_increase_confidence(url):
    evidence = social_presence(
        [{"url": url, "kind": "website", "source": "stonks"}],
        {"stonks": "success"},
    )
    assert evidence["score"] == 0
    assert evidence["links"] == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"score": 0, "score_normalised": 99}, 0),
        ({"score": None, "score_normalised": 0}, 0),
        ({"score_normalised": 0}, 0),
        ({}, None),
    ],
)
def test_rugcheck_fallback_uses_presence_not_truthiness(payload, expected):
    assert report_summary(payload)["score"] == expected


@pytest.mark.parametrize(
    "flags",
    [[], ["--verbose"], ["--json"], ["--verbose", "--json", "--include-raw"]],
)
def test_private_values_stay_out_of_console_logs_and_json(
    monkeypatch, capsys, flags
):
    endpoint = "https://rpc.example/synthetic-private-endpoint"
    key = "synthetic-jupiter-private-key"
    monkeypatch.setattr(settings, "JUPITER_API_KEY", key)
    report = ScanReport("wallet", MINT, "test RPC", STAMP)
    report.summary = {"sol_balance": 1, "diagnostic": endpoint}
    report.findings = [Finding("info", "Echo", f"{endpoint} {key}", "test")]
    report.provider_data = {"jupiter": {"data": {"key": key, "url": endpoint}}}

    def build(*args):
        get_logger("test").warning("Endpoint echoed: %s", endpoint)
        return report

    monkeypatch.setattr(growr, "_build_report", build)
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--rpc-url", endpoint, *flags, "wallet", MINT]
    )
    assert growr.main() == 0
    output = capsys.readouterr()
    assert endpoint not in output.out + output.err
    assert key not in output.out + output.err
    if "--json" in flags:
        document = validate(json.loads(output.out))
        assert document["records"][0]["facts"]["diagnostic"] == "REDACTED"
    assert bool(output.err) == ("--verbose" in flags)


def test_redaction_context_restores_previous_run_and_cleans_raw_keys():
    endpoint = "https://rpc.example/synthetic-private-context"
    with redact_endpoint(endpoint):
        encoded = quote(endpoint, safe="")
        document = serialize({"raw": {endpoint: [encoded]}})
        assert endpoint not in document
        assert encoded not in document
        assert safe_text(endpoint) == "REDACTED"
    assert safe_text(endpoint) == endpoint


def test_public_rpc_default_stays_visible_in_configuration_output():
    public = settings.DEFAULT_PUBLIC_SOLANA_RPC_URL
    with redact_endpoint(public):
        assert safe_text(public) == public
