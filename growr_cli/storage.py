"""Persistence orchestration for normalized Growr listing records."""

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from playhouse.shortcuts import model_to_dict

from growr_cli import __version__
from growr_cli.db import (
    GoodTokenCall,
    ScanRun,
    TokenRecordSnapshot,
    close_database,
    db,
    initialize_database,
)


class GoodCallManager:
    """Manage call history through GoodTokenCall model methods."""

    def __init__(self, database_path=None):
        """Select the SQLite database used for call history."""

        self.database_path = database_path

    def check_good_call(self, mint, timezone_name="UTC", now=None):
        """Check whether a mint was reported today or yesterday."""

        start, now = self._call_window(timezone_name, now)
        try:
            initialize_database(self.database_path)
            call = GoodTokenCall.get_recent_reported_call(mint, start, now)
            return True, {
                "mint": mint,
                "already_reported": call is not None,
                "timezone": timezone_name,
                "window_start": start.isoformat(),
                "checked_at": now.isoformat(),
                "last_call": self._reported_call_data(call, start.tzinfo),
            }
        finally:
            close_database()

    def record_good_call(
        self, values, if_new=False, timezone_name="UTC", now=None
    ):
        """Save a decision, optionally rejecting recent reports."""

        try:
            initialize_database(self.database_path)
            # Keep the write lock across model calls. Separate check and
            # insert transactions would allow duplicate recommendations.
            with db.atomic("IMMEDIATE") as transaction:
                start, now = self._call_window(timezone_name, now)
                if if_new:
                    previous = GoodTokenCall.get_recent_reported_call(
                        values["mint"], start, now
                    )
                    if previous is not None:
                        return True, {
                            "created": False,
                            "already_reported": True,
                            "call": self._reported_call_data(
                                previous, start.tzinfo
                            ),
                        }

                values = dict(values)
                if if_new:
                    values["status"] = "reported"
                values["created_at"] = now.astimezone(timezone.utc)
                success, call = GoodTokenCall.cook_good_call(**values)
                if not success:
                    transaction.rollback()
                    return False, call

                return True, {
                    "created": True,
                    "already_reported": False,
                    "call": model_to_dict(call, recurse=False),
                }
        finally:
            close_database()

    @staticmethod
    def _call_window(timezone_name, now=None):
        """Use yesterday's local midnight through now, including DST."""

        local_zone = ZoneInfo(timezone_name)
        now = now or datetime.now(timezone.utc)
        local_now = now.astimezone(local_zone)
        yesterday = local_now.date() - timedelta(days=1)
        start = datetime.combine(yesterday, time.min, tzinfo=local_zone)
        return start, local_now

    @staticmethod
    def _reported_call_data(call, legacy_timezone):
        """Serialize a returned model for the command response."""

        if call is None:
            return None
        result = model_to_dict(call, recurse=False)
        result["created_at"] = call.created_at_utc(legacy_timezone).isoformat()
        return result


class SnapshotRepository:
    """Store a response as immutable database observations."""

    def __init__(self, database_path=None):
        """Select an optional database file for this repository."""

        self.database_path = database_path

    def store_response(self, response):
        """Persist a response and return counts for the caller."""

        initialize_database(self.database_path)
        try:
            run_data = response["run"]
            request = response["request"]
            options = request.get("options", {})
            records = response.get("records", [])

            with db.atomic():
                run = ScanRun.create(
                    id=run_data["id"],
                    started_at=_datetime(run_data["started_at"]),
                    completed_at=_datetime(run_data["completed_at"]),
                    command=request.get("command") or "unknown",
                    arguments=request,
                    filters=options,
                    provider=options.get("source"),
                    code_version=response["tool"].get("version", __version__),
                    status=response.get("status", "unknown"),
                )

                snapshots = _listing_snapshots(records, run, response)
                if snapshots:
                    TokenRecordSnapshot.insert_many(snapshots).execute()
            return {"run_id": str(run.id), "snapshots": len(snapshots)}
        finally:
            close_database()


class QueryManager:
    """Read stored snapshots without exposing Peewee query objects."""

    def __init__(self, database_path=None):
        """Select the SQLite database used for read operations."""

        self.database_path = database_path

    def get_single_record_by_id(self, pk):
        """Return one snapshot by its database primary key."""

        initialize_database(self.database_path)
        try:
            record = TokenRecordSnapshot.get(TokenRecordSnapshot.id == pk)
            result = model_to_dict(record, recurse=False)
        except Exception as error:
            return False, str(error)
        finally:
            close_database()

        return True, result

    def get_latest_record_by_mint(self, mint):
        """Return the newest stored snapshot for a token mint."""

        initialize_database(self.database_path)
        try:
            query = TokenRecordSnapshot.select().where(
                TokenRecordSnapshot.mint == mint
            )
            query = query.order_by(TokenRecordSnapshot.created_at.desc())
            record = query.first()
            if record is None:
                return False, "no record"
            result = model_to_dict(record, recurse=False)
        except Exception as error:
            return False, str(error)
        finally:
            close_database()

        return True, result

    def get_token_snapshots(self, mint, paginated=False, per_page=10, page=1):
        """Return stored snapshots for a mint, optionally paginated."""

        if per_page < 1 or page < 1:
            return False, "per_page and page must be positive integers"

        initialize_database(self.database_path)
        try:
            snapshots = TokenRecordSnapshot.select().where(
                TokenRecordSnapshot.mint == mint
            )
            snapshots = snapshots.order_by(
                TokenRecordSnapshot.created_at.desc()
            )
            if paginated:
                snapshots = snapshots.paginate(per_page, page)

            clean_snapshots = []
            for snapshot in snapshots:
                clean_snapshots.append(model_to_dict(snapshot, recurse=False))
        except Exception as error:
            return False, str(error)
        finally:
            close_database()

        return True, clean_snapshots


def _is_listing(record):
    return record.get("kind") in {"pool", "token_discovery"}


def _listing_snapshots(records, run, response):
    """Convert valid listing records into database rows."""

    snapshots = []
    for record in records:
        if not _is_listing(record):
            continue

        identity = record.get("identity", {})
        if not identity.get("mint"):
            continue

        snapshot = _snapshot_values(record, run, response)
        snapshots.append(snapshot)

    return snapshots


def _snapshot_values(record, run, response):
    """Translate one machine record into model fields."""

    identity = record.get("identity", {})
    facts = _snapshot_facts(record)
    social = record.get("social") or {}
    request = response.get("request", {})
    options = request.get("options", {})
    source = options.get("source") or facts.get("source") or "unknown"
    observed_at = _datetime(response["run"]["completed_at"])
    return {
        "run": run,
        "observed_at": observed_at,
        "provider": source,
        "query_fingerprint": _fingerprint(request),
        "code_version": response["tool"].get("version", __version__),
        "source_timestamp": _latest_timestamp(record),
        "kind": record.get("kind"),
        "chain": identity.get("chain"),
        "mint": identity.get("mint"),
        "pool": identity.get("pool"),
        "name": identity.get("name"),
        "symbol": identity.get("symbol"),
        "launch_status": facts.get("launch_status"),
        "token_created_at": _datetime(facts.get("created_at")),
        "graduated_at": _datetime(facts.get("graduated_at")),
        "creator": facts.get("creator"),
        "launchpad": facts.get("launchpad"),
        "quote_mint": facts.get("quote_mint"),
        "quote_name": facts.get("quote_name"),
        "quote_symbol": facts.get("quote_symbol"),
        "quote_category": facts.get("quote_category"),
        "graduation_progress": _decimal(facts.get("graduation_progress")),
        "market_cap_usd": _decimal(facts.get("market_cap_usd")),
        "volume_24h_usd": _decimal(facts.get("volume_24h_usd")),
        "price_usd": _decimal(facts.get("price_usd")),
        "fdv_usd": _decimal(facts.get("fdv_usd")),
        "peak_market_cap_usd": _decimal(facts.get("peak_market_cap_usd")),
        "liquidity": _decimal(facts.get("liquidity")),
        "is_reward_launch": facts.get("is_reward_launch"),
        "quote_only_fees": facts.get("quote_only_fees"),
        "metadata_uri": facts.get("metadata_uri"),
        "image_url": facts.get("image_url"),
        "holder_count": facts.get("holder_count"),
        "token_dev": facts.get("token_dev"),
        "organic_score": _decimal(facts.get("organic_score")),
        "organic_score_label": facts.get("organic_score_label"),
        "is_verified": facts.get("is_verified"),
        "token_program": facts.get("token_program"),
        "total_supply": _decimal(facts.get("total_supply")),
        "circulating_supply": _decimal(facts.get("circulating_supply")),
        "mint_disabled": facts.get("mint_disabled"),
        "freeze_authority_disabled": facts.get("freeze_authority_disabled"),
        "top_holders_percentage": _decimal(
            facts.get("top_holders_percentage")
        ),
        "dev_balance_percentage": _decimal(
            facts.get("dev_balance_percentage")
        ),
        "dev_migrations": facts.get("dev_migrations"),
        "dev_mints": facts.get("dev_mints"),
        "transfer_tax_bps": _decimal(facts.get("transfer_tax_bps")),
        "activity_snapshot": facts.get("activity_snapshot"),
        "social_score": social.get("score"),
        "has_website": social.get("has_website"),
        "social_links": social.get("links"),
        "coverage": record.get("coverage"),
        "screen_eligible": None,
        "screen_score": None,
        "screen_rank": None,
        "rejection_reasons": None,
    }


def _snapshot_facts(record):
    """Read Jupiter measurements from the token metric block."""

    facts = dict(record.get("facts", {}))
    if facts.get("source") != "jupiter":
        return facts

    metric = record.get("metrics", {}).get("jupiter", {})
    if metric.get("source") != "jupiter" or metric.get("scope") != "token":
        return facts
    values = metric.get("values", {})
    for field in (
        "price_usd",
        "fdv_usd",
        "liquidity",
        "holder_count",
        "organic_score",
        "organic_score_label",
        "token_program",
        "total_supply",
        "circulating_supply",
        "launchpad",
    ):
        facts[field] = values.get(field)
    facts["market_cap_usd"] = values.get("market_cap")
    facts["token_dev"] = values.get("developer")
    facts["is_verified"] = values.get("verified")
    facts["image_url"] = values.get("icon")
    facts["activity_snapshot"] = values.get("activity")

    activity = values.get("activity") or {}
    daily = activity.get("24h") or {}
    buy_volume = _decimal(daily.get("buyVolume"))
    sell_volume = _decimal(daily.get("sellVolume"))
    if buy_volume is not None and sell_volume is not None:
        facts["volume_24h_usd"] = buy_volume + sell_volume
    return facts


def _fingerprint(request):
    encoded = json.dumps(
        request, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _latest_timestamp(record):
    """Return the latest provider timestamp in a record's coverage."""

    timestamps = []
    for item in record.get("coverage", []):
        fetched_at = item.get("fetched_at")
        if fetched_at:
            timestamps.append(fetched_at)

    if not timestamps:
        return None

    return _datetime(max(timestamps))


def _datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _decimal(value):
    """Convert a value to Decimal and preserve missing data."""

    if value is None:
        return None

    return Decimal(str(value))
