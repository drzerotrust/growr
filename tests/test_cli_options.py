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
    (["list", "dexscreener"], "token_discovery", False),
    (["list", "dexcreener", "--on-chain"], "token_discovery", True),
    (["list", "--community-takeovers"], "token_discovery", False),
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
    pair = {
        "chainId": "solana",
        "pairAddress": OTHER,
        "baseToken": {"address": MINT},
        "priceUsd": "1.5",
        "liquidity": {"usd": 1000},
    }

    if url.startswith(settings.STONKS_API_URL):
        data = {"pools": [{"mint": MINT, "symbol": "GROWR"}]}
    elif url.startswith(settings.JUPITER_API_URL):
        data = [{"id": MINT, "usdPrice": 1.5}]
    elif url.startswith(settings.RUGCHECK_API_URL):
        data = {"score": 0, "risks": []}
    elif "/tokens/v1/solana/" in url:
        data = [pair]
    elif "/latest/dex/tokens/" in url:
        data = {"pairs": [pair]}
    else:
        assert url.endswith(
            ("/token-boosts/latest/v1", "/community-takeovers/latest/v1")
        )
        data = [{"chainId": "solana", "tokenAddress": MINT}]
    return Mock(ok=True, json=Mock(return_value=data))


@pytest.fixture
def offline_io(monkeypatch):
    # Keep parsing, integrations, scanners and rendering real. Replace
    # only network boundaries so options must reach their consumers.
    for name in (
        "DEXSCREENER_API_URL",
        "DEXSCREENER_V1_API_URL",
        "JUPITER_API_URL",
        "STONKS_API_URL",
        "RUGCHECK_API_URL",
    ):
        monkeypatch.setattr(
            settings, name, getattr(settings, f"DEFAULT_{name}").rstrip("/")
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
        if kind == "pool":
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
    coverage = {item["source"]: item["status"] for item in record["coverage"]}
    http_get, _, _ = offline_io
    urls = [call.args[0] for call in http_get.call_args_list]
    for source, base, skipped in (
        ("jupiter", settings.JUPITER_API_URL, skip_jupiter),
        ("rugcheck", settings.RUGCHECK_API_URL, skip_rugcheck),
        ("dexscreener", settings.DEXSCREENER_API_URL, False),
    ):
        requests = sum(url.startswith(base) for url in urls)
        assert requests == (0 if skipped else 1)
        assert coverage[source] == ("skipped" if skipped else "success")
        assert (source in record["raw"]) == (not skipped)


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    ("options", "message"),
    [
        (
            ["--stonk", "--boosted"],
            "Dexscreener feed options cannot select Stonks",
        ),
        (
            ["--stonk", "--community-takeovers"],
            "Dexscreener feed options cannot select Stonks",
        ),
        (
            ["dexscreener", "--stonk-search", "recent"],
            "--stonk-search requires list stonks",
        ),
        (
            ["--boosted", "--stonk-search", "recent"],
            "--stonk-search requires list stonks",
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
        ["list", "dexscreener"],
        ["list", "dexcreener"],
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
    assert output.err == ""
    http.assert_not_called()
    rpc.assert_not_called()
