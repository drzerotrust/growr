from uuid import uuid4

from growr_cli.db import (
    GoodTokenCall,
    ScanRun,
    TokenRecordSnapshot,
    close_database,
    initialize_database,
)
from growr_cli.storage import QueryManager, SnapshotRepository


def test_initialize_database_creates_snapshot_tables(tmp_path):
    initialize_database(tmp_path / "growr.db")
    try:
        run = ScanRun.create(
            id=uuid4(),
            started_at="2026-09-21T12:00:00+00:00",
            command="list",
            arguments={"provider": "stonks"},
            status="completed",
        )
        snapshot = TokenRecordSnapshot.create(
            run=run,
            observed_at="2026-09-21T12:00:00+00:00",
            provider="stonks",
            mint="So11111111111111111111111111111111111111112",
            screen_eligible=True,
            rejection_reasons=None,
        )
        assert snapshot.run.id == run.id
        assert TokenRecordSnapshot.select().count() == 1
    finally:
        close_database()


def test_snapshot_repository_stores_listing_record(tmp_path):
    database_path = tmp_path / "snapshots.db"
    response = {
        "tool": {"version": "test"},
        "run": {
            "id": str(uuid4()),
            "started_at": "2026-09-21T12:00:00+00:00",
            "completed_at": "2026-09-21T12:00:01+00:00",
        },
        "request": {
            "command": "list",
            "options": {"source": "stonks", "mode": "marketCap"},
        },
        "status": "success",
        "records": [
            {
                "kind": "pool",
                "identity": {
                    "chain": "solana",
                    "mint": "So11111111111111111111111111111111111111112",
                    "pool": "Pool1111111111111111111111111111111111111111",
                    "name": "Wrapped SOL",
                    "symbol": "SOL",
                },
                "facts": {
                    "market_cap_usd": 1000000,
                    "price_usd": 1.25,
                    "source": "stonks",
                },
                "social": None,
                "coverage": [],
            }
        ],
    }
    receipt = SnapshotRepository(database_path).store_response(response)
    assert receipt["snapshots"] == 1
    initialize_database(database_path)
    try:
        assert TokenRecordSnapshot.get().market_cap_usd == 1000000
    finally:
        close_database()


def test_latest_snapshot_by_mint_returns_newest_snapshot(tmp_path):
    initialize_database(tmp_path / "latest.db")
    try:
        first_run = ScanRun.create(
            id=uuid4(),
            started_at="2026-09-21T12:00:00+00:00",
            command="list",
            arguments={},
            status="completed",
        )
        second_run = ScanRun.create(
            id=uuid4(),
            started_at="2026-09-21T13:00:00+00:00",
            command="list",
            arguments={},
            status="completed",
        )
        mint = "So11111111111111111111111111111111111111112"
        TokenRecordSnapshot.create(
            run=first_run,
            observed_at="2026-09-21T12:00:00+00:00",
            created_at="2026-09-21T12:00:00+00:00",
            provider="stonks",
            mint=mint,
        )
        newest = TokenRecordSnapshot.create(
            run=second_run,
            observed_at="2026-09-21T13:00:00+00:00",
            created_at="2026-09-21T13:00:00+00:00",
            provider="stonks",
            mint=mint,
        )

        success, snapshot = TokenRecordSnapshot.get_latest_snapshot_by_mint(
            mint
        )

        assert success is True
        assert snapshot.id == newest.id
    finally:
        close_database()


def test_latest_snapshot_by_mint_reports_missing_mint(tmp_path):
    initialize_database(tmp_path / "missing.db")
    try:
        success, snapshot = TokenRecordSnapshot.get_latest_snapshot_by_mint(
            "So11111111111111111111111111111111111111112"
        )

        assert success is False
        assert snapshot is None
    finally:
        close_database()


def test_cook_good_call_creates_agent_decision(tmp_path):
    initialize_database(tmp_path / "calls.db")
    try:
        run = ScanRun.create(
            id=uuid4(),
            started_at="2026-09-21T12:00:00+00:00",
            command="list",
            arguments={},
            status="completed",
        )
        snapshot = TokenRecordSnapshot.create(
            run=run,
            observed_at="2026-09-21T12:00:00+00:00",
            provider="stonks",
            mint="So11111111111111111111111111111111111111112",
        )

        success, call = GoodTokenCall.cook_good_call(
            mint=snapshot.mint,
            snapshot_id=snapshot,
            decision="buy",
            confidence="high",
        )

        assert success is True
        assert call.snapshot_id.id == snapshot.id
        assert call.decision == "buy"
    finally:
        close_database()


def test_query_manager_reads_snapshot_records(tmp_path):
    database_path = tmp_path / "query.db"
    initialize_database(database_path)
    try:
        run = ScanRun.create(
            id=uuid4(),
            started_at="2026-09-21T12:00:00+00:00",
            command="list",
            arguments={},
            status="completed",
        )
        mint = "So11111111111111111111111111111111111111112"
        first = TokenRecordSnapshot.create(
            run=run,
            observed_at="2026-09-21T12:00:00+00:00",
            created_at="2026-09-21T12:00:00+00:00",
            provider="stonks",
            mint=mint,
        )
        TokenRecordSnapshot.create(
            run=run,
            observed_at="2026-09-21T13:00:00+00:00",
            created_at="2026-09-21T13:00:00+00:00",
            provider="stonks",
            mint=mint,
        )
    finally:
        close_database()

    manager = QueryManager(database_path)
    success, record = manager.get_single_record_by_id(first.id)
    assert success is True
    assert record["id"] == first.id

    success, records = manager.get_token_snapshots(
        mint, paginated=True, per_page=1, page=1
    )
    assert success is True
    assert len(records) == 1

    success, missing = manager.get_latest_record_by_mint("missing")
    assert success is False
    assert missing == "no record"
