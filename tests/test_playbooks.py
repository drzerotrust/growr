"""Subprocess boundaries and token-to-wallet investigation evidence."""

import json
import subprocess
import sys
from copy import deepcopy
from unittest.mock import Mock

import pytest
from solders.pubkey import Pubkey

from growr_cli.models import ScanReport
from scripts.playbooks import token_holders, wallet_holdings
from scripts.playbooks.holdings import (
    MintResolver,
    group_accounts,
    sampled_owners,
    wallet_inventory,
)
from scripts.playbooks.runner import PROJECT_ROOT, GrowrRunner
from tests.test_machine import STAMP, output_for


def address(index):
    return str(Pubkey.from_bytes(bytes([index]) * 32))


MINT = address(1)
OWNER = address(2)
SECOND_OWNER = address(3)
OTHER_MINT = address(4)
THIRD_MINT = address(5)


def holder(index, owner, raw):
    return {
        "token_account": address(index),
        "owner": owner,
        "raw_amount": str(raw),
        "ui_amount": 0,
        "percent_of_supply": 0,
    }


def account(index, mint, raw, program="spl_token", state="initialized"):
    return {
        "address": address(index),
        "mint": mint,
        "raw_amount": str(raw),
        "token_program": program,
        "state": state,
    }


def token_document(mint=MINT, holders=(), decimals=2, program="spl_token"):
    report = ScanReport(
        "token",
        mint,
        "offline RPC",
        STAMP,
        summary={
            "mint": {
                "decimals": decimals,
                "token_program": program,
                "supply": "18446744073709551615",
            },
            "metadata": {"name": "Example", "symbol": "EX"},
            "holders": {"top_accounts": list(holders)},
        },
    )
    return output_for(report, "token", mint, "--no-jupiter", "--no-rugcheck")


def wallet_document(owner=OWNER, entries=(), failed_program=None):
    inventory = {
        "entries": list(entries),
        "spl_token_account_count": sum(
            entry["token_program"] == "spl_token" for entry in entries
        ),
        "token_2022_account_count": sum(
            entry["token_program"] == "token_2022" for entry in entries
        ),
        "total_account_count": len(entries),
        "unparsed_account_count": 0,
    }
    if failed_program:
        inventory["%s_account_count" % failed_program] = None
        inventory["%s_error" % failed_program] = "RPC unavailable"
    report = ScanReport(
        "wallet",
        owner,
        "offline RPC",
        STAMP,
        summary={"sol_balance": 1.5, "token_accounts": inventory},
    )
    return output_for(report, "wallet", owner)


def child_commands(monkeypatch, documents):
    def run(command, **kwargs):
        assert command[:4] == [
            sys.executable,
            str(PROJECT_ROOT / "growr.py"),
            "--json",
            "--no-color",
        ]
        assert kwargs["cwd"] == PROJECT_ROOT
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        kind, target = command[4:6]
        if kind == "search":
            assert target == "jupiter"
            assert len(command) == 7
            target = command[6]
        elif kind == "history":
            assert command[6:8] == ["--limit", "10"]
            assert len(command) == 8
        else:
            assert command[6:] == (
                ["--no-jupiter", "--no-rugcheck"] if kind == "token" else []
            )
        result = documents[(kind, target)]
        if isinstance(result, Exception):
            raise result
        if isinstance(result, subprocess.CompletedProcess):
            return result
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(result), stderr="private diagnostic"
        )

    process = Mock(side_effect=run)
    monkeypatch.setattr("scripts.playbooks.runner.subprocess.run", process)
    return process


def test_token_playbook_aggregates_owners_and_reuses_mint_scans(
    monkeypatch, capsys
):
    maximum = 18446744073709551615
    documents = {
        ("token", MINT): token_document(
            holders=[
                holder(10, SECOND_OWNER, 800),
                holder(11, OWNER, 600),
                holder(12, OWNER, 500),
            ]
        ),
        ("wallet", OWNER): wallet_document(
            entries=[
                account(11, MINT, 600),
                account(12, MINT, 500),
                account(13, OTHER_MINT, maximum, "token_2022", "frozen"),
                account(14, OTHER_MINT, 10, "token_2022"),
                account(15, THIRD_MINT, 0),
            ]
        ),
        ("wallet", SECOND_OWNER): wallet_document(
            SECOND_OWNER,
            [
                account(10, MINT, 800),
                account(16, OTHER_MINT, 123, "token_2022"),
            ],
        ),
        ("token", OTHER_MINT): token_document(
            OTHER_MINT, decimals=9, program="token_2022"
        ),
    }
    process = child_commands(monkeypatch, documents)

    assert (
        token_holders.main(
            [
                MINT,
                "--no-jupiter",
                "--json",
                "--mint-limit",
                "1",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    assert report["playbook_version"] == "1.1"
    assert report["status"] == "success"
    assert report["sample"]["resolved_nonzero_owners"] == 2
    assert [wallet["address"] for wallet in report["wallets"]] == [
        OWNER,
        SECOND_OWNER,
    ]
    first = report["wallets"][0]
    assert first["sample_raw_amount"] == "1100"
    assert first["sample_amount_tokens"] == "11"
    assert first["zero_accounts_omitted"] == 1
    target, other = first["holdings"]
    assert target["is_target"] is True
    assert target["amount_tokens"] == "11"
    assert other["raw_amount"] == "18446744073709551625"
    assert other["amount_tokens"] == "18446744073.709551625"
    assert other["accounts"][0]["state"] == "frozen"
    assert len(other["accounts"]) == 2
    assert (
        report["wallets"][1]["holdings"][1]["amount_tokens"] == "0.000000123"
    )
    assert [call.args[0][4:6] for call in process.call_args_list] == [
        ["token", MINT],
        ["wallet", OWNER],
        ["wallet", SECOND_OWNER],
        ["token", OTHER_MINT],
    ]
    assert report["budget"]["subprocesses_attempted"] == 4
    assert report["budget"]["rpc_calls_upper_estimate"] == 16
    assert all(scan["run"]["id"] for scan in report["scans"])
    assert "private diagnostic" not in output.out


def test_owner_limit_unresolved_accounts_and_zero_balances(
    monkeypatch, capsys
):
    process = child_commands(
        monkeypatch,
        {
            ("token", MINT): token_document(
                holders=[
                    holder(10, None, 9999),
                    holder(11, OWNER, 10),
                    holder(12, SECOND_OWNER, 5),
                    holder(13, address(6), 0),
                ]
            ),
            ("wallet", OWNER): wallet_document(),
        },
    )
    assert (
        token_holders.main(
            [
                MINT,
                "--no-jupiter",
                "--json",
                "--wallet-limit",
                "1",
                "--mint-limit",
                "0",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["sample"]["owners_not_selected"] == 1
    assert report["sample"]["unresolved_accounts"][0]["raw_amount"] == "9999"
    assert report["wallets"][0]["holdings"] == []
    assert process.call_count == 2


@pytest.mark.parametrize("mint_limit", [0, 1])
def test_mint_budget_retains_every_holding(monkeypatch, capsys, mint_limit):
    process = child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 100), account(11, OTHER_MINT, 200)]
            ),
            ("token", MINT): token_document(),
        },
    )
    assert (
        wallet_holdings.main(
            [
                OWNER,
                "--no-jupiter",
                "--json",
                "--mint-limit",
                str(mint_limit),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    holdings = report["wallets"][0]["holdings"]
    assert len(holdings) == 2
    assert holdings[1]["amount_tokens"] is None
    assert holdings[1]["raw_amount"] == "200"
    assert holdings[1]["amount_status"] == (
        "budget_exhausted" if mint_limit else "not_requested"
    )
    assert report["status"] == ("partial" if mint_limit else "success")
    assert process.call_count == 1 + mint_limit


def test_failed_wallet_does_not_discard_other_owner(monkeypatch, capsys):
    child_commands(
        monkeypatch,
        {
            ("token", MINT): token_document(
                holders=[holder(10, OWNER, 20), holder(11, SECOND_OWNER, 10)]
            ),
            ("wallet", OWNER): subprocess.TimeoutExpired(
                "private-endpoint", 1, output="secret", stderr="secret"
            ),
            ("wallet", SECOND_OWNER): wallet_document(SECOND_OWNER),
        },
    )
    assert (
        token_holders.main(
            [
                MINT,
                "--no-jupiter",
                "--json",
                "--mint-limit",
                "0",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "partial"
    assert report["wallets"][0]["holdings"] is None
    assert report["wallets"][1]["holdings"] == []
    assert report["scans"][1]["error"] == "child_timeout"
    assert "secret" not in output.out + output.err


def test_partial_program_inventory_keeps_known_balance(monkeypatch, capsys):
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, OTHER_MINT, 42)],
                failed_program="token_2022",
            )
        },
    )
    assert (
        wallet_holdings.main(
            [
                OWNER,
                "--no-jupiter",
                "--json",
                "--mint-limit",
                "0",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["wallets"][0]["inventory_complete"] is False
    assert report["wallets"][0]["holdings"][0]["raw_amount"] == "42"
    assert any(
        item["operation"] == "token_2022_inventory"
        for item in report["scans"][0]["coverage"]
    )


def test_empty_token_sample_does_not_scan_wallets(monkeypatch, capsys):
    process = child_commands(monkeypatch, {("token", MINT): token_document()})
    assert (
        token_holders.main(
            [MINT, "--no-jupiter", "--mint-limit", "10", "--json"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "no_data"
    assert report["wallets"] == []
    assert process.call_count == 1


@pytest.mark.parametrize(
    "script,kind,target",
    [
        (token_holders, "token", MINT),
        (wallet_holdings, "wallet", OWNER),
    ],
)
def test_initial_scan_failure_is_structured(
    monkeypatch, capsys, script, kind, target
):
    process = child_commands(
        monkeypatch,
        {
            (kind, target): subprocess.CompletedProcess(
                [], 1, "secret", "secret"
            )
        },
    )
    assert script.main([target, "--json"]) == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "error"
    assert report["scans"][0]["error"] == "growr_failed"
    assert "secret" not in output.out + output.err
    assert process.call_count == 1


@pytest.mark.parametrize(
    "output",
    ["[]", "null", "{}", "log\n{}", "{}\n{}", '{"x": NaN}', '{"x": 1e999}'],
)
def test_runner_rejects_invalid_child_output(monkeypatch, output):
    child_commands(
        monkeypatch,
        {
            ("token", MINT): subprocess.CompletedProcess(
                [], 0, output, "secret"
            )
        },
    )
    runner = GrowrRunner(30, 1)
    assert runner.scan("token", MINT) is None
    assert runner.scans[0]["error"] == "invalid_growr_output"


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "9.0"),
        ("request", {"command": "wallet", "target": MINT}),
        ("request", {"command": "token", "target": OTHER_MINT}),
        ("records", []),
        ("tool", None),
        ("run", {}),
    ],
)
def test_runner_rejects_mismatched_contract(monkeypatch, field, value):
    document = token_document()
    document[field] = value
    child_commands(monkeypatch, {("token", MINT): document})
    runner = GrowrRunner(30, 1)
    assert runner.scan("token", MINT) is None
    assert runner.scans[0]["error"] == "invalid_growr_output"


def test_failed_mint_is_cached_without_retry(monkeypatch):
    process = child_commands(
        monkeypatch, {("token", MINT): OSError("private error")}
    )
    resolver = MintResolver(GrowrRunner(30, 3), 3)
    assert resolver.resolve(MINT)["status"] == "failed"
    assert resolver.resolve(MINT)["status"] == "failed"
    assert resolver.lookups == process.call_count == 1


def test_runner_hard_cap_stops_before_second_process(monkeypatch):
    process = child_commands(monkeypatch, {("token", MINT): token_document()})
    runner = GrowrRunner(30, 1)
    assert runner.scan("token", MINT)
    with pytest.raises(ValueError, match="budget exceeded"):
        runner.scan("token", MINT)
    assert process.call_count == 1


def test_full_playbook_with_real_fixture_subprocesses(
    monkeypatch, tmp_path, capsys
):
    documents = {
        ("token", MINT): token_document(holders=[holder(10, OWNER, 123)]),
        ("wallet", OWNER): wallet_document(
            entries=[account(10, MINT, 123), account(11, OTHER_MINT, 1234)]
        ),
        ("token", OTHER_MINT): token_document(OTHER_MINT, decimals=3),
    }
    for (kind, target), document in documents.items():
        (tmp_path / ("%s_%s.json" % (kind, target))).write_text(
            json.dumps(document)
        )
    (tmp_path / "growr.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "kind, target = sys.argv[3:5]\n"
        "path = Path(__file__).parent / ('%s_%s.json' % (kind, target))\n"
        "print(path.read_text())\n"
        "print('private child diagnostic', file=sys.stderr)\n"
    )
    monkeypatch.setattr("scripts.playbooks.runner.PROJECT_ROOT", tmp_path)

    assert (
        token_holders.main(
            [
                MINT,
                "--no-jupiter",
                "--json",
                "--mint-limit",
                "1",
            ]
        )
        == 0
    )

    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "success"
    assert report["budget"]["subprocesses_attempted"] == 3
    assert report["wallets"][0]["holdings"][1]["amount_tokens"] == "1.234"
    assert output.err == ""
    assert "private child diagnostic" not in output.out


def test_mint_program_mismatch_keeps_raw_balance(monkeypatch, capsys):
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 123)]
            ),
            ("token", MINT): token_document(program="token_2022"),
        },
    )
    assert (
        wallet_holdings.main(
            [OWNER, "--no-jupiter", "--mint-limit", "10", "--json"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    assert holding["amount_status"] == "program_mismatch"
    assert holding["raw_amount"] == "123"
    assert holding["amount_tokens"] is None
    assert report["status"] == "partial"


@pytest.mark.parametrize("decimals", [0, 255])
def test_extreme_mint_decimals_remain_exact(monkeypatch, capsys, decimals):
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(entries=[account(10, MINT, 1)]),
            ("token", MINT): token_document(decimals=decimals),
        },
    )
    assert (
        wallet_holdings.main(
            [OWNER, "--no-jupiter", "--mint-limit", "10", "--json"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    expected = "0." + "0" * 254 + "1" if decimals else "1"
    assert holding["amount_tokens"] == expected


@pytest.mark.parametrize("main", [token_holders.main, wallet_holdings.main])
@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["invalid"],
        [MINT, "--mint-limit", "-1"],
        [MINT, "--timeout", "0"],
        [MINT, "--mint-limit", "51"],
    ],
)
def test_invalid_options_are_offline(monkeypatch, main, arguments):
    process = child_commands(monkeypatch, {})
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    process.assert_not_called()


@pytest.mark.parametrize("module", ["token_holders", "wallet_holdings"])
def test_playbook_help_runs_as_a_real_subprocess(module):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.playbooks.%s" % module, "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "Examples:" in result.stdout
    assert "--mint-limit" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("script", ["token_holders", "wallet_holdings"])
def test_direct_script_help_works_outside_project(script, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "playbooks" / ("%s.py" % script)),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "Examples:" in result.stdout
    assert result.stderr == ""


def test_real_growr_child_is_resolved_from_another_directory(
    monkeypatch, tmp_path
):
    # An invalid command variant avoids network while exercising actual
    # interpreter, path, capture, environment and JSON failure behavior.
    monkeypatch.chdir(tmp_path)
    from scripts.playbooks import runner as runner_module

    original = subprocess.run

    def reject_command(command, **kwargs):
        command[4] = "scan"
        return original(command, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "run", reject_command)
    runner = GrowrRunner(10, 1)
    assert runner.scan("token", MINT) is None
    assert runner.scans[0]["returncode"] == 2
    assert runner.scans[0]["error"] == "growr_failed"


@pytest.mark.parametrize("raw", ["1.1", "-1", "1e9", 123, "١٢٣"])
def test_malformed_raw_balances_are_not_aggregated(raw):
    entry = account(10, MINT, 1)
    entry["raw_amount"] = raw
    with pytest.raises(ValueError, match="raw balance"):
        group_accounts([entry], MINT)


def test_duplicate_accounts_are_not_double_counted():
    entry = account(10, MINT, 42)
    with pytest.raises(ValueError, match="wallet account"):
        group_accounts([entry, deepcopy(entry)], MINT)
    document = token_document(holders=[holder(10, OWNER, 42)] * 2)
    with pytest.raises(ValueError, match="repeated sample account"):
        sampled_owners(document["records"][0], 5)


def test_missing_inventory_does_not_become_empty():
    record = wallet_document()["records"][0]
    del record["facts"]["token_accounts"]["entries"]
    result = wallet_inventory(OWNER, record)
    assert result["status"] == "failed"
    assert result["holdings"] is None


def test_both_programs_unavailable_do_not_become_empty(monkeypatch, capsys):
    document = wallet_document(failed_program="token_2022")
    inventory = document["records"][0]["facts"]["token_accounts"]
    inventory["spl_token_account_count"] = None
    inventory["total_account_count"] = None
    inventory["spl_token_error"] = "RPC unavailable"
    process = child_commands(monkeypatch, {("wallet", OWNER): document})

    assert (
        wallet_holdings.main(
            [OWNER, "--no-jupiter", "--mint-limit", "10", "--json"]
        )
        == 0
    )

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "partial"
    assert report["wallets"][0]["holdings"] is None
    assert report["wallets"][0]["inventory_complete"] is False
    assert process.call_count == 1


def test_console_reports_exact_units_and_sanitizes_names(monkeypatch, capsys):
    document = token_document(decimals=9)
    document["records"][0]["facts"]["metadata"]["name"] = "Unsafe\x1b[2J\nname"
    child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[
                    account(10, MINT, 18446744073709551615),
                    account(11, MINT, 10),
                ]
            ),
            ("token", MINT): document,
        },
    )
    assert (
        wallet_holdings.main([OWNER, "--no-jupiter", "--mint-limit", "10"])
        == 0
    )
    output = capsys.readouterr()
    assert MINT in output.out
    assert "18,446,744,073.709551625 tokens" in output.out
    assert "%s: 18,446,744,073.709551615 tokens" % address(10) in output.out
    assert "%s: 0.00000001 tokens" % address(11) in output.out
    assert "\x1b" not in output.out
    assert "Unsafe[2Jname" in output.out
    assert output.err == ""

    assert (
        wallet_holdings.main(
            [OWNER, "--no-jupiter", "--mint-limit", "10", "--json"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    holding = report["wallets"][0]["holdings"][0]
    assert holding["amount_tokens"] == "18446744073.709551625"
    assert holding["raw_amount"] == "18446744073709551625"
    assert holding["accounts"][0]["raw_amount"] == "18446744073709551615"


def test_console_unknown_decimals_never_become_token_quantities(
    monkeypatch, capsys
):
    process = child_commands(
        monkeypatch,
        {
            ("wallet", OWNER): wallet_document(
                entries=[account(10, MINT, 1234567890)]
            ),
        },
    )
    assert wallet_holdings.main([OWNER, "--no-jupiter"]) == 0
    output = capsys.readouterr()
    assert "1,234,567,890 raw units (not_requested)" in output.out
    assert "%s: 1,234,567,890 raw units [initialized]" % address(10) in (
        output.out
    )
    assert "1,234,567,890 tokens" not in output.out
    assert process.call_count == 1


def test_playbooks_consume_cli_without_importing_workflows():
    import ast

    for path in (PROJECT_ROOT / "scripts" / "playbooks").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("growr")
            elif isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("growr") for alias in node.names
                )
