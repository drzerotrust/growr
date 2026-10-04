"""Combined Jupiter discovery with fair samples and shared limits."""

import json
import subprocess
from functools import partial
from unittest.mock import Mock

import pytest

from growr_cli.playbooks import token_screen
from tests.test_token_screen import (
    MINT,
    OTHER_MINT,
    THIRD_MINT,
    address,
    criteria,
    discovery,
    ranking,
    rpc_document,
    rule,
    write_json,
)
from tests.test_token_screen_discovery import discovery_for

FEEDS = ["recent", "toptrending", "toptraded", "toporganicscore"]


def run_child(argv, documents, **kwargs):
    assert kwargs["shell"] is False
    command = argv[9:]
    key = command[1]
    if command[0] == "list":
        key = command[command.index("--jupiter-search") + 1]
    document = documents[key]
    if isinstance(document, Exception):
        raise document
    return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")


def feed_document(feed, mints, limit=50, **values):
    command = ["list", "jupiter", "--jupiter-search", feed]
    if feed != "recent":
        command.extend(["--interval", "1h", "--limit", str(limit)])
    document = discovery_for(command)
    if mints:
        document["records"] = discovery(mints, **values)["records"]
    else:
        document["records"] = []
        document["status"] = "no_data"
    return document


def run_screen(monkeypatch, tmp_path, capsys, documents, settings, *flags):
    process = Mock(side_effect=partial(run_child, documents=documents))
    monkeypatch.setattr("growr_cli.playbooks.runner.subprocess.run", process)
    config = write_json(tmp_path, "criteria.json", settings)
    code = token_screen.main(
        [
            "--criteria",
            config,
            "--provider",
            "jupiter",
            "--feeds",
            *FEEDS,
            "--interval",
            "1h",
            *flags,
            "--json",
        ]
    )
    output = capsys.readouterr()
    assert output.err == ""
    return code, json.loads(output.out), process


def test_all_feeds_read_before_fair_deduplicated_sample(
    monkeypatch, tmp_path, capsys
):
    fourth, fifth = address(30), address(31)
    groups = [
        [MINT, OTHER_MINT, THIRD_MINT],
        [MINT, THIRD_MINT],
        [fourth],
        [MINT, fifth],
    ]
    documents = {}
    for feed, mints in zip(FEEDS, groups, strict=True):
        documents[feed] = feed_document(feed, mints, limit=4)
    code, report, process = run_screen(
        monkeypatch,
        tmp_path,
        capsys,
        documents,
        criteria(),
        "--candidate-limit",
        "4",
    )

    assert code == 0
    assert process.call_count == 4
    assert report["scope"]["selected_mints"] == [
        MINT,
        THIRD_MINT,
        fourth,
        fifth,
    ]
    assert report["scope"]["candidates_available"] == 5
    assert report["scope"]["candidates_omitted"] == 1
    assert report["budget"]["reserved_upper_bounds"] == {"rpc": 0, "http": 4}
    receipts = report["scope"]["feeds"]
    assert [row["scan_index"] for row in receipts] == [0, 1, 2, 3]
    assert [row["records_returned"] for row in receipts] == [3, 2, 1, 2]
    commands = [call.args[0][9:] for call in process.call_args_list]
    assert commands[0] == ["list", "jupiter", "--jupiter-search", "recent"]
    for feed, command in zip(FEEDS[1:], commands[1:], strict=True):
        assert command == [
            "list",
            "jupiter",
            "--jupiter-search",
            feed,
            "--interval",
            "1h",
            "--limit",
            "4",
        ]

    # Replay retains source receipts and every selected observation.
    saved = write_json(tmp_path, "screen.json", report)
    config = str(tmp_path / "criteria.json")
    assert (
        token_screen.main(["--criteria", config, "--input", saved, "--json"])
        == 0
    )
    replay = json.loads(capsys.readouterr().out)
    assert replay["counts"] == report["counts"]
    assert replay["evidence"] == report["evidence"]
    assert replay["scope"]["source_scope"]["feeds"] == receipts
    assert replay["budget"]["subprocesses_attempted"] == 0
    assert process.call_count == 4


def test_failed_and_empty_feeds_do_not_hide_later_candidates(
    monkeypatch, tmp_path, capsys
):
    documents = {
        "recent": subprocess.TimeoutExpired("growr", 30),
        "toptrending": feed_document("toptrending", []),
        "toptraded": feed_document("toptraded", [MINT]),
        "toporganicscore": feed_document("toporganicscore", [OTHER_MINT]),
    }
    code, report, process = run_screen(
        monkeypatch, tmp_path, capsys, documents, criteria()
    )
    assert code == 0
    assert process.call_count == 4
    assert report["status"] == "partial"
    assert report["counts"]["matched"] == 2
    assert [row["status"] for row in report["scope"]["feeds"]] == [
        "failed",
        "no_data",
        "success",
        "success",
    ]
    assert report["budget"]["reserved_upper_bounds"]["http"] == 4
    assert report["budget"]["measured"]["unmeasured_children"] >= 1


@pytest.mark.parametrize("http_limit", [0, 2, 4])
def test_multi_feed_http_budget_includes_failures(
    monkeypatch, tmp_path, capsys, http_limit
):
    documents = dict.fromkeys(FEEDS, subprocess.TimeoutExpired("growr", 30))
    code, report, process = run_screen(
        monkeypatch,
        tmp_path,
        capsys,
        documents,
        criteria(),
        "--max-http-calls",
        str(http_limit),
    )
    assert code == 1
    assert process.call_count == http_limit
    assert report["budget"]["reserved_upper_bounds"]["http"] == http_limit
    skipped = report["scope"]["feeds"][http_limit:]
    assert all(row["status"] == "not_requested" for row in skipped)
    assert all(row["scan_index"] is None for row in skipped)


def test_empty_feeds_are_successful_empty_screen(
    monkeypatch, tmp_path, capsys
):
    documents = {feed: feed_document(feed, []) for feed in FEEDS}
    code, report, process = run_screen(
        monkeypatch, tmp_path, capsys, documents, criteria()
    )
    assert code == 0
    assert process.call_count == 4
    assert report["status"] == "no_data"
    assert report["gaps"] == []


@pytest.mark.parametrize("budget,scanned", [(80, 20), (8, 2)])
def test_verification_skips_failures_and_scans_each_mint_once(
    monkeypatch, tmp_path, capsys, budget, scanned
):
    mints = [address(number) for number in range(1, 23)]
    documents = {}
    for feed in FEEDS:
        document = feed_document(feed, mints, limit=100, mcap=10000)
        document["records"][0]["metrics"]["jupiter"]["values"][
            "market_cap"
        ] = 1
        documents[feed] = document
    for mint in mints[1:]:
        documents[mint] = rpc_document(mint)
    code, report, process = run_screen(
        monkeypatch,
        tmp_path,
        capsys,
        documents,
        criteria(
            rule("market_cap_usd", 10000),
            verify=True,
            ranking=[ranking("top_20_accounts_pct", "asc")],
        ),
        "--candidate-limit",
        "100",
        "--scan-limit",
        "20",
        "--max-rpc-calls",
        str(budget),
        "--max-http-calls",
        "4",
    )
    assert code == 0
    commands = [call.args[0][9:] for call in process.call_args_list]
    verified = [command[1] for command in commands if command[0] == "token"]
    assert len(verified) == len(set(verified)) == scanned
    assert mints[0] not in verified
    assert report["budget"]["reserved_upper_bounds"] == {
        "rpc": scanned * 4,
        "http": 4,
    }
    assert report["counts"]["rejected"] == 1
    assert report["counts"]["unknown"] == 21 - scanned


@pytest.mark.parametrize(
    "flags",
    [
        ["--provider", "stonks", "--feeds", "recent"],
        ["--provider", "jupiter", "--feeds", "recent", "recent"],
        ["--provider", "jupiter", "--feeds", "volume"],
        ["--provider", "jupiter", "--feeds", "recent", "--interval", "1h"],
        ["--provider", "jupiter", "--feeds", "recent", "--feed", "recent"],
        ["--provider", "jupiter", "--feeds", "recent", "--query", "JUP"],
        ["--mints", MINT, "--feeds", "recent"],
        ["--input", "unused.json", "--feeds", "recent"],
    ],
)
def test_bad_multi_feed_options_fail_before_children(monkeypatch, flags):
    process = Mock()
    monkeypatch.setattr("growr_cli.playbooks.runner.subprocess.run", process)
    with pytest.raises(SystemExit) as error:
        token_screen.main(["--criteria", "unused.json", *flags])
    assert error.value.code == 2
    process.assert_not_called()
