"""Versioned JSON contracts, failures, raw opt-in, and provenance."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import growr
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.integrations.http import provider_result
from growr_cli.machine.response import Run, build_response, serialize
from growr_cli.machine.schema import response_schema
from growr_cli.models import (
    EnrichmentResult,
    ProviderStatus,
    ScanReport,
    SearchReport,
    TokenSearches,
)
from growr_cli.solana.rpc import RpcError
from tests.test_enrichment import MINT, enricher, launch_report, providers_for

STAMP = "2026-09-09T12:00:00+00:00"


def validate(document):
    Draft202012Validator(
        response_schema(), format_checker=FormatChecker()
    ).validate(document)
    return document


def output_for(report, *command, raw=False):
    flags = ["--json", "--include-raw"] if raw else ["--json"]
    parser = growr.build_parser()
    args = parser.parse_args([*flags, *command])
    growr._validate_search_arguments(parser, args)
    return validate(json.loads(serialize(build_response(Run(), args, report))))


@pytest.mark.parametrize("kind", ["token", "wallet", "token_account"])
@pytest.mark.parametrize("raw", [False, True])
def test_scan_records_have_consistent_envelope(kind, raw):
    report = ScanReport(kind, MINT, "RPC", STAMP, summary={"sol_balance": 0})
    document = output_for(report, kind.replace("_", "-"), MINT, raw=raw)
    assert document["schema_version"] == "2.2"
    assert document["status"] == "success"
    record = document["records"][0]
    assert record["kind"] == kind
    assert record["facts"]["sol_balance"] == 0
    assert ("raw" in record) == raw
    assert record["coverage"][0]["fetched_at"] is None
    assert document["error"] is None
    assert document["pagination"] is None


@pytest.mark.parametrize("mode", ["recent", "marketCap", "volume"])
@pytest.mark.parametrize(
    "outcome", ["success", "failed", "not_configured", "no_data"]
)
def test_stonks_schema_and_partial_status(mode, outcome):
    report = launch_report()
    report.search_type = "stonk-%s" % mode
    client = providers_for([MINT])
    client.jupiter.get_tokens.return_value[MINT] = EnrichmentResult(
        outcome, STAMP, {"id": MINT} if outcome == "success" else None
    )
    enricher(client).enrich(report)
    document = output_for(report, "list", "--stonk", "--stonk-search", mode)
    expected = (
        "partial" if outcome in {"failed", "not_configured"} else "success"
    )
    assert document["status"] == expected
    assert document["records"][0]["kind"] == "pool"
    assert "raw" not in document
    assert "raw" not in document["records"][0]


@pytest.mark.parametrize("source", ["stonk", "jupiter"])
def test_empty_discovery_is_a_valid_no_data_result(source):
    tokens = {"pools": []} if source == "stonk" else []
    report = SearchReport(
        "recent", TokenSearches(tokens, 0.0, source, "no_data")
    )
    flags = ["--stonk"] if source == "stonk" else ["jupiter"]
    document = output_for(report, "list", *flags)
    assert document["status"] == "no_data"
    assert document["records"] == []
    assert document["coverage"][0]["status"] == "no_data"


def test_wallet_partial_reads_and_secrets_are_explicit(monkeypatch):
    monkeypatch.setattr("growr_cli.settings.HELIUS_API_KEY", "private-key")
    report = ScanReport(
        "wallet",
        MINT,
        "Helius",
        STAMP,
        summary={
            "token_accounts": {
                "spl_token_error": "https://rpc.test?api-key=private-key",
                "total_account_count": 2,
            },
        },
    )
    document = output_for(report, "wallet", MINT)
    assert document["status"] == "partial"
    assert "private-key" not in json.dumps(document)
    assert (
        document["records"][0]["facts"]["token_accounts"][
            "total_account_count"
        ]
        == 2
    )


def test_skipped_and_no_data_providers_do_not_mark_partial():
    report = ScanReport(
        "token",
        MINT,
        "RPC",
        STAMP,
        providers=[ProviderStatus("Jupiter", "no_data", "No token")],
    )
    document = output_for(report, "token", MINT, "--no-rugcheck")
    assert document["status"] == "success"
    statuses = {
        item["source"]: item["status"] for item in document["coverage"]
    }
    assert statuses["rugcheck"] == "skipped"
    assert statuses["jupiter"] == "no_data"


def test_http_payloads_retained_without_repeat_fetches():
    jupiter, rugcheck = Mock(), Mock()
    payload = {"id": MINT, "usdPrice": 1, "extra": "raw-only"}
    jupiter.get_token.return_value = provider_result("success", payload)
    rugcheck.get_report.return_value = provider_result("no_data")
    report = ScanReport("token", MINT, "RPC", STAMP)
    TokenContext(jupiter, rugcheck).enrich(report, MINT, True, True)
    document = output_for(report, "token", MINT)
    assert "raw-only" not in json.dumps(document)
    document = output_for(report, "token", MINT, raw=True)
    assert document["records"][0]["raw"]["jupiter"] == payload
    assert document["records"][0]["coverage"][1]["fetched_at"]
    jupiter.get_token.assert_called_once_with(MINT)
    rugcheck.get_report.assert_called_once_with(MINT)


def test_discovery_raw_extras_and_order_are_preserved():
    report = launch_report(
        [{"mint": MINT, "pool": "a"}, {"mint": MINT, "pool": "b"}]
    )
    report.raw["featured"] = {"mint": "featured-only"}
    client = providers_for([MINT])
    for provider in (client.jupiter,):
        provider.get_tokens.return_value[MINT].fetched_at = STAMP
    enricher(client).enrich(report)
    document = output_for(report, "list", "--stonk", raw=True)
    assert [item["identity"]["pool"] for item in document["records"]] == [
        "a",
        "b",
    ]
    assert document["raw"]["discovery"]["featured"] == {
        "mint": "featured-only"
    }
    assert all(
        "analytics" not in item
        for item in document["raw"]["discovery"]["pools"]
    )
    client.jupiter.get_tokens.assert_called_once_with([MINT])


@pytest.mark.parametrize("failed", [False, True])
def test_nested_rpc_uses_scan_contract_and_failure_coverage(failed):
    report = launch_report()
    client = providers_for([MINT])
    for provider in (client.jupiter,):
        provider.get_tokens.return_value[MINT].fetched_at = STAMP
    scan = Mock(return_value=ScanReport("token", MINT, "RPC", STAMP))
    if failed:
        scan.side_effect = RpcError("unavailable")
    enricher(client, scan).enrich(report)
    document = output_for(report, "list", "--stonk", "--on-chain")
    record = document["records"][0]
    assert document["status"] == ("partial" if failed else "success")
    assert (record["on_chain"] is None) == failed
    if not failed:
        assert record["on_chain"]["kind"] == "token"


def test_strict_json_preserves_integer_strings_and_reports_nan():
    report = ScanReport(
        "token",
        MINT,
        "RPC",
        STAMP,
        summary={
            "mint": {"supply": "123456789012345678901234567890"},
            "unknown": float("nan"),
            "infinity": float("inf"),
            "zero": 0,
        },
    )
    document = output_for(report, "token", MINT)
    assert document["status"] == "partial"
    facts = document["records"][0]["facts"]
    assert facts["mint"]["supply"] == "123456789012345678901234567890"
    assert facts["unknown"] is None and facts["infinity"] is None
    assert facts["zero"] == 0
    assert any(
        item["operation"] == "normalization" for item in document["coverage"]
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["no-command"],
        ["list"],
        ["token", "invalid-secret-address"],
        ["token"],
        ["list", "--stonk", "--category", "bad-secret"],
        ["list", "--page", "no-secret"],
        ["list", "jupiter", "--stonk"],
        ["list", "--unknown=secret"],
    ],
)
def test_json_argument_errors_never_echo_invalid_values(
    monkeypatch, capsys, arguments
):
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", *arguments])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    assert growr.main() == 2
    captured = capsys.readouterr()
    document = validate(json.loads(captured.out))
    assert document["error"]["code"] == "INVALID_ARGUMENTS"
    assert "secret" not in captured.out + captured.err
    http.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ValueError("secret"), "EXECUTION_FAILED"),
        (RpcError("secret"), "RPC_ERROR"),
        (RuntimeError("secret"), "INTERNAL_ERROR"),
    ],
)
def test_cli_error_codes_and_cleanup(monkeypatch, capsys, failure, code):
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", "token", MINT])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", Mock(return_value=http))
    monkeypatch.setattr(growr, "_build_report", Mock(side_effect=failure))
    assert growr.main() == 1
    captured = capsys.readouterr()
    document = validate(json.loads(captured.out))
    assert document["error"]["code"] == code
    assert document["records"] == []
    assert "secret" not in captured.out + captured.err
    http.close.assert_called_once()


def test_serialization_failure_is_one_error_document(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", "wallet", MINT])
    report = ScanReport(
        "wallet", MINT, "RPC", STAMP, summary={"unsupported": object()}
    )
    monkeypatch.setattr(growr, "_build_report", Mock(return_value=report))
    assert growr.main() == 1
    document = validate(json.loads(capsys.readouterr().out))
    assert document["error"]["code"] == "INTERNAL_ERROR"


def test_schema_command_is_offline(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["growr.py", "schema"])
    http = Mock()
    rpc = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    assert growr.main() == 0
    document = json.loads(capsys.readouterr().out)
    Draft202012Validator.check_schema(document)
    assert document == response_schema()
    http.assert_not_called()
    rpc.assert_not_called()


def test_raw_requires_json(monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--include-raw", "wallet", MINT]
    )
    with pytest.raises(SystemExit) as error:
        growr.main()
    assert error.value.code == 2


def test_schema_rejects_broken_contracts():
    report = ScanReport("wallet", MINT, "RPC", STAMP)
    document = output_for(report, "wallet", MINT)
    validator = Draft202012Validator(response_schema())
    for key in ("schema_version", "status", "records", "coverage", "error"):
        invalid = deepcopy(document)
        invalid.pop(key)
        assert not validator.is_valid(invalid)
    document["status"] = "error"
    assert not validator.is_valid(document)


@pytest.mark.parametrize("command", ["token", "wallet", "token-account"])
def test_actual_scan_workflows_emit_valid_machine_records(
    monkeypatch, capsys, command
):
    from solders.pubkey import Pubkey

    from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID
    from tests.conftest import make_mint_bytes, make_token_account_bytes

    rpc = Mock()
    rpc.parse_address.side_effect = Pubkey.from_string
    rpc.get_balance_sol.return_value = 2.0
    rpc.get_signatures.return_value = []
    rpc.get_token_accounts_by_owner.return_value = []
    rpc.get_largest_token_accounts.return_value = []
    rpc.get_multiple_accounts.return_value = []
    rpc.find_metadata_address.return_value = Pubkey.from_string(MINT)
    if command == "token":
        rpc.get_account_data.side_effect = [
            (make_mint_bytes(), str(SPL_TOKEN_PROGRAM_ID)),
            (None, None),
        ]
    else:
        rpc.get_account_data.return_value = (
            make_token_account_bytes(),
            str(SPL_TOKEN_PROGRAM_ID),
        )
    monkeypatch.setattr(growr, "SolanaRpcClient", Mock(return_value=rpc))
    monkeypatch.setattr(
        "growr_cli.integrations.http.requests.Session.get",
        Mock(
            return_value=Mock(ok=True, json=Mock(return_value={"pairs": []}))
        ),
    )
    flags = ["--no-jupiter", "--no-rugcheck"] if command == "token" else []
    monkeypatch.setattr(
        "sys.argv", ["growr.py", "--json", command, MINT, *flags]
    )
    renderer = Mock(
        side_effect=AssertionError(
            "Machine output must bypass console renderers"
        )
    )
    monkeypatch.setattr(growr, "renderer_for", renderer)
    assert growr.main() == 0
    captured = capsys.readouterr()
    document = validate(json.loads(captured.out))
    assert document["records"][0]["kind"] == command.replace("-", "_")
    assert document["status"] == "success"
    assert captured.err == ""
    rpc.close.assert_called_once()
    renderer.assert_not_called()


def test_schema_rejects_numeric_raw_token_amounts():
    report = ScanReport(
        "token", MINT, "RPC", STAMP, summary={"mint": {"supply": "1000"}}
    )
    document = output_for(report, "token", MINT)
    document["records"][0]["facts"]["mint"]["supply"] = 1000
    assert not Draft202012Validator(response_schema()).is_valid(document)


def test_malformed_optional_discovery_text_remains_schema_valid():
    report = SearchReport(
        "recent",
        TokenSearches(
            [{"id": MINT, "symbol": [], "description": {"bad": 1}}],
            0.0,
            "jupiter",
            "success",
        ),
    )
    document = output_for(report, "list", "jupiter")
    assert document["status"] == "partial"
    assert document["records"][0]["identity"]["symbol"] is None
    assert document["records"][0]["facts"]["description"] is None
