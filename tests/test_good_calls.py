"""Call history, calendar boundaries and duplicate prevention."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

import growr
from growr_cli import db as database
from growr_cli.db import (
    GoodTokenCall,
    ScanRun,
    TokenRecordSnapshot,
    close_database,
    initialize_database,
)
from growr_cli.storage import GoodCallManager

MINT = "So11111111111111111111111111111111111111112"
OTHER = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
NOW = datetime(2026, 10, 2, 18, tzinfo=timezone.utc)


@pytest.fixture
def snapshot_db(tmp_path, monkeypatch):
    path = tmp_path / "calls.db"
    monkeypatch.setattr(database, "DATABASE_PATH", path)
    initialize_database(path)
    try:
        run = ScanRun.create(
            id=uuid4(),
            started_at=NOW,
            command="list",
            arguments={},
            status="success",
        )
        snapshot = TokenRecordSnapshot.create(
            run=run,
            mint=MINT,
            provider="jupiter",
            observed_at=NOW,
        )
        snapshot_id = snapshot.id
    finally:
        close_database()
    return path, snapshot_id


def run_cli(monkeypatch, capsys, arguments):
    monkeypatch.setattr("sys.argv", ["growr.py", "--json", *arguments])
    http = Mock(side_effect=AssertionError("No HTTP expected"))
    rpc = Mock(side_effect=AssertionError("No RPC expected"))
    monkeypatch.setattr(growr, "HttpClient", http)
    monkeypatch.setattr(growr, "SolanaRpcClient", rpc)
    code = growr.main()
    output = capsys.readouterr()
    assert output.err == ""
    http.assert_not_called()
    rpc.assert_not_called()
    return code, json.loads(output.out)


def test_check_snapshot_does_not_mean_reported(
    snapshot_db, monkeypatch, capsys
):
    code, result = run_cli(monkeypatch, capsys, ["good-call", MINT, "--check"])
    assert code == 0
    assert result["data"]["already_reported"] is False
    assert result["data"]["last_call"] is None
    assert result["data"]["timezone"] == "UTC"


def test_cli_records_only_once_and_returns_call_fields(
    snapshot_db, monkeypatch, capsys
):
    path, snapshot_id = snapshot_db
    arguments = [
        "good-call",
        MINT,
        "--snapshot-id",
        str(snapshot_id),
        "--if-new",
        "--timezone",
        "America/Mexico_City",
        "--decision",
        "fallback",
        "--reasons",
        "Weak organic score",
    ]
    code, first = run_cli(monkeypatch, capsys, arguments)
    assert code == 0
    assert first["data"]["created"] is True
    call = first["data"]["call"]
    assert call["mint"] == MINT
    assert call["snapshot_id"] == snapshot_id
    assert call["status"] == "reported"
    assert call["decision"] == "fallback"
    assert call["created_at"].endswith("+00:00")

    code, second = run_cli(monkeypatch, capsys, arguments)
    assert code == 0
    assert second["data"]["created"] is False
    assert second["data"]["already_reported"] is True
    assert second["data"]["call"]["id"] == call["id"]

    code, check = run_cli(
        monkeypatch,
        capsys,
        ["good-call", MINT, "--check", "--timezone", "America/Mexico_City"],
    )
    assert code == 0
    assert check["data"]["already_reported"] is True
    assert check["data"]["last_call"]["id"] == call["id"]

    initialize_database(path)
    try:
        assert GoodTokenCall.select().count() == 1
    finally:
        close_database()


@pytest.mark.parametrize(
    ("created_at", "status", "mint", "expected"),
    [
        ("2026-10-01T06:00:00+00:00", "reported", MINT, True),
        ("2026-10-01T05:59:59+00:00", "reported", MINT, False),
        ("2026-10-02T17:59:59+00:00", "reported", MINT, True),
        ("2026-10-02T18:00:00+00:00", "reported", MINT, True),
        ("2026-10-02T18:00:01+00:00", "reported", MINT, False),
        ("2026-10-02T12:00:00+00:00", "draft", MINT, False),
        ("2026-10-02T12:00:00+00:00", None, MINT, False),
        ("2026-10-02T12:00:00+00:00", "reported", OTHER, False),
        ("2026-10-01T00:00:00", "reported", MINT, True),
        ("2026-09-30T23:59:59", "reported", MINT, False),
    ],
)
def test_only_reported_calls_in_local_calendar_window_count(
    snapshot_db, created_at, status, mint, expected
):
    path, snapshot_id = snapshot_db
    initialize_database(path)
    try:
        GoodTokenCall.create(
            mint=mint,
            snapshot_id=snapshot_id,
            status=status,
            created_at=created_at,
            agent_id="another-agent",
        )
    finally:
        close_database()
    manager = GoodCallManager(path)
    success, result = manager.check_good_call(MINT, "America/Mexico_City", NOW)
    assert success
    assert result["already_reported"] is expected
    assert result["window_start"] == "2026-10-01T00:00:00-06:00"


def test_calendar_window_handles_dst(snapshot_db):
    path, snapshot_id = snapshot_db
    manager = GoodCallManager(path)
    moment = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    manager.record_good_call(
        {"mint": MINT, "snapshot_id": snapshot_id, "status": "reported"},
        now=datetime(2026, 11, 1, 4, tzinfo=timezone.utc),
    )
    success, result = manager.check_good_call(MINT, "America/New_York", moment)
    assert success
    assert result["window_start"] == "2026-11-01T00:00:00-04:00"
    assert result["checked_at"] == "2026-11-02T07:00:00-05:00"
    assert result["already_reported"] is True


def test_expired_call_can_be_reported_again(snapshot_db):
    path, snapshot_id = snapshot_db
    manager = GoodCallManager(path)
    values = {"mint": MINT, "snapshot_id": snapshot_id}
    manager.record_good_call(
        values,
        True,
        now=datetime(2026, 9, 30, 23, tzinfo=timezone.utc),
    )
    success, result = manager.record_good_call(values, True, now=NOW)
    assert success
    assert result["created"] is True


@pytest.mark.parametrize("snapshot_id,mint", [(999, MINT), (None, OTHER)])
def test_invalid_snapshot_cannot_record_call(snapshot_db, snapshot_id, mint):
    path, existing_id = snapshot_db
    manager = GoodCallManager(path)
    success, _ = manager.record_good_call(
        {"mint": mint, "snapshot_id": snapshot_id or existing_id},
        True,
    )
    assert success is False
    success, result = manager.check_good_call(mint)
    assert success
    assert result["already_reported"] is False


@pytest.mark.parametrize("snapshot_id,mint", [(999, MINT), (None, OTHER)])
def test_model_rejects_invalid_snapshot_with_borrowed_connection(
    snapshot_db, snapshot_id, mint
):
    path, existing_id = snapshot_db
    initialize_database(path)
    try:
        success, _ = GoodTokenCall.cook_good_call(
            mint=mint, snapshot_id=snapshot_id or existing_id
        )
        assert success is False
        assert GoodTokenCall.select().count() == 0
        assert database.db.is_closed() is False
    finally:
        close_database()


def test_manager_closes_database_when_model_lookup_fails(
    snapshot_db, monkeypatch
):
    path, _ = snapshot_db
    query = Mock(side_effect=RuntimeError("Query failed"))
    monkeypatch.setattr(GoodTokenCall, "select", query)

    with pytest.raises(RuntimeError, match="Query failed"):
        GoodCallManager(path).check_good_call(MINT)

    assert database.db.is_closed()


def test_manager_rolls_back_failed_model_write(snapshot_db, monkeypatch):
    path, snapshot_id = snapshot_db
    # Simulate a model operation that writes before reporting failure.
    # Its tuple outcome must not cause the manager to commit that write.
    monkeypatch.setattr(
        GoodTokenCall, "cook_good_call", classmethod(write_then_fail)
    )
    success, error = GoodCallManager(path).record_good_call(
        {"mint": MINT, "snapshot_id": snapshot_id}, if_new=True
    )
    assert success is False
    assert error == "Database operation failed"
    assert database.db.is_closed()

    initialize_database(path)
    try:
        assert GoodTokenCall.select().count() == 0
    finally:
        close_database()


def write_then_fail(model, **values):
    model.create(**values)
    return False, "Database operation failed"


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--check", "--snapshot-id", "1"],
        ["--check", "--if-new"],
        ["--check", "--status", "reported"],
        ["--check", "--timezone", "invalid-zone"],
        ["--snapshot-id", "0"],
        ["--snapshot-id", "bad"],
        ["--snapshot-id", "1", "--if-new", "--status", "draft"],
    ],
)
def test_invalid_arguments_fail_before_database(monkeypatch, capsys, options):
    database_call = Mock(side_effect=AssertionError("Must fail in parser"))
    monkeypatch.setattr(growr, "run_good_call", database_call)
    code, result = run_cli(monkeypatch, capsys, ["good-call", MINT, *options])
    assert code == 2
    assert result["error"]["code"] == "INVALID_ARGUMENTS"
    database_call.assert_not_called()


def test_database_failure_is_not_a_new_token(monkeypatch, capsys):
    monkeypatch.setattr(
        growr,
        "run_good_call",
        Mock(side_effect=OSError("private-path credentials")),
    )
    code, result = run_cli(monkeypatch, capsys, ["good-call", MINT, "--check"])
    assert code == 1
    assert result == {
        "command": "good-call",
        "status": "error",
        "error": "Database operation failed",
    }


def test_overlapping_processes_only_create_one_call(snapshot_db, tmp_path):
    path, snapshot_id = snapshot_db
    config = tmp_path / "empty.env"
    config.write_text("")
    environment = dict(
        os.environ, GROWR_DATABASE_PATH=str(path), GROWR_ENV_FILE=str(config)
    )
    command = [
        sys.executable,
        "-m",
        "growr",
        "--json",
        "good-call",
        MINT,
        "--snapshot-id",
        str(snapshot_id),
        "--if-new",
    ]
    processes = []
    for _ in range(2):
        processes.append(
            subprocess.Popen(
                command,
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        assert stderr == ""
        results.append(json.loads(stdout)["data"]["created"])
    assert sorted(results) == [False, True]
