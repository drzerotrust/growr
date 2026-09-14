"""Exercise CLI options through real workflows with offline I/O."""

import json
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

import growr
from growr_cli import settings
from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID
from tests.conftest import make_mint_bytes, make_token_account_bytes
from tests.test_enrichment import MINT, OTHER
from tests.test_machine import validate

RPC_OVERRIDE = "https://override.example/private-review-endpoint"
COMMANDS = [
    (["token", MINT], "token", True),
    (["wallet", OTHER], "wallet", True),
    (["token-account", OTHER], "token_account", True),
    (["list", "stonks"], "pool", False),
    (["list", "--stonk", "--on-chain"], "pool", True),
    (["list", "jupiter"], "token_discovery", False),
    (["list", "jupiter", "--on-chain"], "token_discovery", True),
    (["search", "jupiter", "JUP"], "token_discovery", False),
    (["search", "stonks", "te"], "pool", False),
]
OUTPUT_OPTIONS = [
    [],
    ["--no-color"],
    ["--verbose"],
    ["--quiet"],
    ["--json"],
    ["--json", "--verbose", "--no-color"],
    ["--json", "--quiet"],
    ["--json", "--include-raw"],
]


def provider_response(url, **options):
    if url.startswith(settings.STONKS_API_URL):
        data = {
            "data": {"tokens": [{"mint": MINT, "symbol": "GROWR"}]},
            "meta": {},
        }
    elif url.startswith(settings.JUPITER_API_URL):
        data = [{"id": MINT, "usdPrice": 1.5}]
    elif url.startswith(settings.RUGCHECK_API_URL):
        data = {"score": 0, "risks": []}
    else:
        raise AssertionError("Unexpected provider URL: %s" % url)
    return Mock(ok=True, json=Mock(return_value=data))


@pytest.fixture
def offline_io(monkeypatch):
    # Keep parsing, integrations, scanners and rendering real. Replace
    # only network boundaries so options must reach their consumers.
    for name in (
        "JUPITER_API_URL",
        "STONKS_API_URL",
        "RUGCHECK_API_URL",
    ):
        monkeypatch.setattr(
            settings,
            name,
            getattr(settings, "DEFAULT_%s" % name).rstrip("/"),
        )
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "synthetic-review-key")
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_VALUE", "5")

    http_get = Mock(side_effect=provider_response)
    monkeypatch.setattr("requests.Session.get", http_get)

    def account_data(address):
        if str(address) == MINT:
            return make_mint_bytes(), str(SPL_TOKEN_PROGRAM_ID)
        if str(address) == OTHER:
            return make_token_account_bytes(), str(SPL_TOKEN_PROGRAM_ID)
        return None, None

    clients = []

    def rpc_client(*arguments):
        client = Mock()
        client.parse_address.side_effect = Pubkey.from_string
        client.get_account_data.side_effect = account_data
        client.find_metadata_address.return_value = Pubkey.from_bytes(
            bytes([7]) * 32
        )
        client.get_balance_sol.return_value = 2.5
        client.get_signatures.return_value = []
        client.get_token_accounts_by_owner.return_value = []
        client.get_largest_token_accounts.return_value = []
        client.get_multiple_accounts.return_value = []
        clients.append(client)
        return client

    rpc_factory = Mock(side_effect=rpc_client)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc_factory)
    return http_get, rpc_factory, clients


@pytest.mark.parametrize(("command", "kind", "uses_rpc"), COMMANDS)
@pytest.mark.parametrize("flags", OUTPUT_OPTIONS)
def test_command_output_options(
    monkeypatch, capsys, offline_io, command, kind, uses_rpc, flags
):
    monkeypatch.setattr(
        "sys.argv",
        ["growr.py", "--rpc-url", RPC_OVERRIDE, *flags, *command],
    )

    assert growr.main() == 0

    output = capsys.readouterr()
    assert output.out
    assert "\x1b" not in output.out + output.err
    assert RPC_OVERRIDE not in output.out + output.err
    assert bool(output.err) == ("--verbose" in flags)
    if "--json" in flags:
        report = validate(json.loads(output.out))
        assert report["status"] == "success"
        assert report["records"][0]["kind"] == kind
        assert ("raw" in report["records"][0]) == ("--include-raw" in flags)
        assert report["request"]["rpc"] == (
            "CLI --rpc-url override" if uses_rpc else None
        )
        if kind == "pool" and command[0] == "list":
            assert report["request"]["options"]["mode"] == "recent"

    _, rpc_factory, clients = offline_io
    assert bool(clients) == uses_rpc
    for call in rpc_factory.call_args_list:
        assert call.args == (RPC_OVERRIDE, 5)
    for client in clients:
        client.close.assert_called_once()


@pytest.mark.parametrize("skip_jupiter", [False, True])
@pytest.mark.parametrize("skip_rugcheck", [False, True])
def test_token_provider_flags_control_requests_and_coverage(
    monkeypatch, capsys, offline_io, skip_jupiter, skip_rugcheck
):
    options = ["--no-jupiter"] if skip_jupiter else []
    options += ["--no-rugcheck"] if skip_rugcheck else []
    monkeypatch.setattr(
        "sys.argv",
        [
            "growr.py",
            "--rpc-url",
            RPC_OVERRIDE,
            "--json",
            "--include-raw",
            "token",
            MINT,
            *options,
        ],
    )

    assert growr.main() == 0

    output = capsys.readouterr()
    assert output.err == ""
    report = validate(json.loads(output.out))
    assert report["status"] == "success"
    record = report["records"][0]
    assert (record["social"] is None) == skip_jupiter
    coverage = {item["source"]: item["status"] for item in record["coverage"]}
    http_get, _, _ = offline_io
    urls = [call.args[0] for call in http_get.call_args_list]
    for source, base, skipped in (
        ("jupiter", settings.JUPITER_API_URL, skip_jupiter),
        ("rugcheck", settings.RUGCHECK_API_URL, skip_rugcheck),
    ):
        requests = sum(url.startswith(base) for url in urls)
        assert requests == (0 if skipped else 1)
        assert coverage[source] == ("skipped" if skipped else "success")
        assert (source in record["raw"]) == (not skipped)


@pytest.mark.parametrize("json_mode", [False, True])
def test_token_jupiter_metrics_and_links_stay_separate_from_rpc(
    monkeypatch, capsys, offline_io, json_mode
):
    payload = {
        "id": MINT,
        "usdPrice": 0,
        "liquidity": 120,
        "organicScore": 0,
        "audit": {"mintAuthorityDisabled": False},
        "stats5m": {"buyVolume": 10, "sellVolume": 0},
        "firstPool": {"id": OTHER},
        "website": "https://project.example",
        "twitter": "https://x.com/project",
        "telegram": "https://t.me/project",
        "extra": "raw-only",
    }

    def get(url, **options):
        if url.startswith(settings.JUPITER_API_URL):
            return Mock(ok=True, json=Mock(return_value=[payload]))
        return provider_response(url, **options)

    http_get, _, _ = offline_io
    http_get.side_effect = get
    flags = ["--json", "--include-raw"] if json_mode else []
    monkeypatch.setattr("sys.argv", ["growr.py", *flags, "token", MINT])
    assert growr.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert http_get.call_count == 2
    if not json_mode:
        assert "Jupiter reported audit" in output.out
        assert "Jupiter trading activity" in output.out
        assert "100/100" in output.out
        assert "https://project.example" in output.out
        assert "raw-only" not in output.out
        return

    record = validate(json.loads(output.out))["records"][0]
    assert record["facts"]["source"] == "rpc"
    assert not {"jupiter", "market", "social"} & record["facts"].keys()
    metrics = record["metrics"]["jupiter"]
    assert metrics["source"] == "jupiter" and metrics["scope"] == "token"
    assert metrics["values"]["price_usd"] == 0
    assert metrics["values"]["liquidity"] == 120
    assert metrics["values"]["audit"] == payload["audit"]
    assert metrics["values"]["activity"]["5m"] == payload["stats5m"]
    assert metrics["values"]["first_pool"] == {"id": OTHER}
    assert record["social"]["score"] == 100
    assert all(
        link["sources"] == ["jupiter"] for link in record["social"]["links"]
    )
    assert record["raw"]["jupiter"] == payload


@pytest.mark.parametrize("outcome", ["missing_key", "failed", "no_data"])
def test_jupiter_gaps_preserve_direct_rpc_report(
    monkeypatch, capsys, offline_io, outcome
):
    http_get, _, _ = offline_io

    def get(url, **options):
        if url.startswith(settings.JUPITER_API_URL):
            return Mock(
                ok=outcome != "failed",
                status_code=503,
                json=Mock(return_value=[]),
            )
        return provider_response(url, **options)

    http_get.side_effect = get
    if outcome == "missing_key":
        monkeypatch.setattr(settings, "JUPITER_API_KEY", None)
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", "token", MINT])
    assert growr.main() == 0
    document = validate(json.loads(capsys.readouterr().out))
    assert document["status"] == (
        "success" if outcome == "no_data" else "partial"
    )
    record = document["records"][0]
    assert record["facts"]["mint"]["supply"] == "1000"
    assert record["social"]["score"] == 0
    expected = "not_configured" if outcome == "missing_key" else outcome
    assert record["social"]["coverage"] == {"jupiter": expected}
    assert http_get.call_count == (1 if outcome == "missing_key" else 2)


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            ["stonks", "--query", "JUP"],
            "unrecognized arguments: --query JUP",
        ),
        (
            ["jupiter", "--stonk"],
            "--stonk conflicts with the Jupiter provider",
        ),
        (
            ["jupiter", "--stonk-search", "recent"],
            "--stonk-search requires list stonks",
        ),
        (
            ["stonks", "--jupiter-search", "recent"],
            "Jupiter search options require list jupiter",
        ),
    ],
)
def test_provider_conflicts_fail_before_network(
    monkeypatch, capsys, json_mode, options, message
):
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr("sys.argv", ["growr.py", *flags, "list", *options])
    http = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)

    if json_mode:
        assert growr.main() == 2
    else:
        with pytest.raises(SystemExit) as error:
            growr.main()
        assert error.value.code == 2
    http.assert_not_called()
    output = capsys.readouterr()
    if json_mode:
        report = validate(json.loads(output.out))
        assert report["error"]["code"] == "INVALID_ARGUMENTS"
        assert output.err == ""
    else:
        assert output.out == ""
        assert message in output.err


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
@pytest.mark.parametrize(
    "command",
    [
        [],
        ["schema"],
        ["token"],
        ["wallet"],
        ["token-account"],
        ["list"],
        ["list", "stonks"],
        ["list", "jupiter"],
        ["search"],
        ["search", "jupiter"],
        ["search", "jupiter", "JUP"],
        ["search", "stonks"],
        ["search", "stonks", "te"],
    ],
)
def test_every_help_route_is_offline_with_examples(
    monkeypatch, capsys, command, help_flag
):
    monkeypatch.setattr(settings, "RPC_URL", "invalid-unused-config")
    monkeypatch.setattr(settings, "STONKS_API_URL", "invalid-unused-config")
    http = Mock()
    rpc = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    monkeypatch.setattr("sys.argv", ["growr.py", *command, help_flag])

    with pytest.raises(SystemExit) as error:
        growr.main()

    assert error.value.code == 0
    output = capsys.readouterr()
    assert "usage:" in output.out
    assert "Examples:" in output.out
    assert "growr.py scan " not in output.out
    assert "alias: scan" not in output.out
    assert output.err == ""
    http.assert_not_called()
    rpc.assert_not_called()


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("options", [[MINT], [MINT, "--stonk"], ["--help"]])
def test_removed_scan_command_fails_before_network(
    monkeypatch, capsys, json_mode, options
):
    flags = ["--json"] if json_mode else []
    monkeypatch.setattr("sys.argv", ["growr.py", *flags, "scan", *options])
    http = Mock()
    rpc = Mock()
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)

    if json_mode:
        assert growr.main() == 2
    else:
        with pytest.raises(SystemExit) as error:
            growr.main()
        assert error.value.code == 2

    output = capsys.readouterr()
    if json_mode:
        report = validate(json.loads(output.out))
        assert report["error"]["code"] == "INVALID_ARGUMENTS"
        assert output.err == ""
    else:
        assert "invalid choice: 'scan'" in output.err
        # Argparse versions differ in how they quote valid choices.
        choices = output.err.partition("(choose from ")[2].partition(")")[0]
        choices = {choice.strip(" '\"") for choice in choices.split(",")}
        assert "token" in choices
        assert "scan" not in choices
        assert output.out == ""
    http.assert_not_called()
    rpc.assert_not_called()
