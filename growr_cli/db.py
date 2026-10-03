"""SQLite persistence models for Growr observations.

The database layer is independent from the web application. Scanners
produce normalized machine records; this module stores scan runs and
token snapshots.
"""

import datetime
from pathlib import Path

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
    UUIDField,
)
from playhouse.sqlite_ext import JSONField

from growr_cli.environment import database_file

DATABASE_PATH = database_file()

db = SqliteDatabase(
    str(DATABASE_PATH),
    pragmas={"journal_mode": "wal", "cache_size": -64000},
)


class BaseModel(Model):
    """Base model bound to the Growr SQLite database."""

    class Meta:
        database = db


class ScanRun(BaseModel):
    """One invocation that produced one or more token snapshots."""

    id = UUIDField(primary_key=True)
    started_at = DateTimeField()
    completed_at = DateTimeField(null=True)
    command = TextField()
    arguments = JSONField()
    filters = JSONField(null=True)
    provider = CharField(max_length=64, null=True)
    code_version = CharField(max_length=64, null=True)
    status = CharField(max_length=32)


class TokenRecordSnapshot(BaseModel):
    """Immutable token facts and results at one observation time."""

    id = AutoField()
    run = ForeignKeyField(ScanRun, backref="snapshots", index=True)

    # Observation identity
    observed_at = DateTimeField(index=True)
    provider = CharField(max_length=64, index=True)
    query_fingerprint = CharField(max_length=64, null=True, index=True)
    code_version = CharField(max_length=64, null=True)
    source_timestamp = DateTimeField(null=True)

    # Token identity
    kind = CharField(max_length=64, null=True)
    chain = CharField(max_length=32, null=True)
    mint = CharField(max_length=64, index=True)
    pool = CharField(max_length=64, null=True)
    name = CharField(max_length=255, null=True)
    symbol = CharField(max_length=64, null=True)

    # Listing and market facts
    launch_status = CharField(max_length=64, null=True)
    token_created_at = DateTimeField(null=True)
    graduated_at = DateTimeField(null=True)
    creator = CharField(max_length=64, null=True)
    launchpad = CharField(max_length=64, null=True)
    quote_mint = CharField(max_length=64, null=True)
    quote_name = CharField(max_length=255, null=True)
    quote_symbol = CharField(max_length=64, null=True)
    quote_category = CharField(max_length=64, null=True)
    graduation_progress = DecimalField(null=True)
    market_cap_usd = DecimalField(null=True)
    volume_24h_usd = DecimalField(null=True)
    price_usd = DecimalField(null=True)
    fdv_usd = DecimalField(null=True)
    peak_market_cap_usd = DecimalField(null=True)
    liquidity = DecimalField(null=True)
    is_reward_launch = BooleanField(null=True)
    quote_only_fees = BooleanField(null=True)
    metadata_uri = TextField(null=True)
    image_url = TextField(null=True)

    # Distribution and risk facts
    holder_count = IntegerField(null=True)
    token_dev = CharField(max_length=64, null=True)
    organic_score = DecimalField(null=True)
    organic_score_label = CharField(max_length=64, null=True)
    is_verified = BooleanField(null=True)
    token_program = CharField(max_length=64, null=True)
    total_supply = DecimalField(null=True)
    circulating_supply = DecimalField(null=True)
    mint_disabled = BooleanField(null=True)
    freeze_authority_disabled = BooleanField(null=True)
    top_holders_percentage = DecimalField(null=True)
    dev_balance_percentage = DecimalField(null=True)
    dev_migrations = IntegerField(null=True)
    dev_mints = IntegerField(null=True)
    transfer_tax_bps = DecimalField(null=True)

    # Enrichment and provenance
    activity_snapshot = JSONField(null=True)
    social_score = IntegerField(null=True)
    has_website = BooleanField(null=True)
    social_links = JSONField(null=True)
    coverage = JSONField(null=True)

    # Screening outcome
    screen_eligible = BooleanField(null=True)
    screen_score = DecimalField(null=True)
    screen_rank = IntegerField(null=True)
    rejection_reasons = JSONField(null=True)
    created_at = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def get_latest_snapshot_by_mint(cls, mint):
        """Return the newest snapshot for a mint.

        Returns:
            A ``(success, value)`` tuple. On success, ``value`` is the
            snapshot. Missing data returns ``(False, None)``.
            Failures return an error description.
        """

        try:
            snapshots = cls.select().where(cls.mint == mint)
            snapshots = snapshots.order_by(cls.created_at.desc())
            snapshot = snapshots.first()
        except Exception as error:
            return False, str(error)

        if snapshot is None:
            return False, None

        return True, snapshot


class GoodTokenCall(BaseModel):
    """Record an agent's decision that a token met its strategy."""

    id = AutoField()
    mint = CharField(max_length=255, null=True)
    snapshot_id = ForeignKeyField(TokenRecordSnapshot)
    agent_id = CharField(max_length=255, null=True)
    agent_version = CharField(max_length=255, null=True)
    strategy = CharField(max_length=255, null=True)
    decision = CharField(max_length=255, null=True)
    confidence = CharField(max_length=255, null=True)
    criteria = CharField(max_length=255, null=True)
    reasons = CharField(max_length=255, null=True)
    status = CharField(max_length=255, null=True)
    created_at = DateTimeField(default=datetime.datetime.now)

    @classmethod
    def get_recent_reported_call(cls, mint, start, now):
        """Return the latest reported call in the supplied date window.

        The caller owns the connection and any transaction. Return None
        for no match; query failures propagate to the manager.
        """

        calls = cls.select().where(
            (cls.mint == mint) & (cls.status == "reported")
        )
        latest = None
        latest_time = None
        for call in calls:
            created_at = call.created_at_utc(start.tzinfo)
            if not start <= created_at <= now:
                continue
            if latest_time is None or created_at > latest_time:
                latest = call
                latest_time = created_at

        return latest

    def created_at_utc(self, legacy_timezone) -> datetime.datetime:
        """Read the creation time as UTC without changing the record."""

        created_at = self.created_at
        if not created_at:
            raise ValueError("Reported call has no creation time")
        if not isinstance(created_at, datetime.datetime):
            created_at = datetime.datetime.fromisoformat(
                str(created_at).replace("Z", "+00:00")
            )

        # New calls carry UTC offsets. Interpret legacy naive times
        # in the explicitly selected calendar timezone.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=legacy_timezone)
        return created_at.astimezone(datetime.timezone.utc)

    @classmethod
    def cook_good_call(cls, **data):
        """Validate the snapshot and create an agent decision record."""

        try:
            snapshot = TokenRecordSnapshot.get_or_none(
                TokenRecordSnapshot.id == data.get("snapshot_id")
            )
            if snapshot is None:
                return False, "Snapshot not found"
            if snapshot.mint != data.get("mint"):
                return False, "Snapshot belongs to another mint"

            good_call = cls.create(**data)
        except Exception:
            return False, "Database operation failed"

        return True, good_call


class CallOutcome(BaseModel):
    """Record the later market outcome used to evaluate a call."""

    id = AutoField()
    call = ForeignKeyField(GoodTokenCall)
    evaluation_time = DateTimeField(default=datetime.datetime.now)
    horizon = CharField(max_length=255, null=True)
    price_at_decision = DecimalField(null=True)
    price_after = DecimalField(null=True)
    return_pct = DecimalField(null=True)
    max_drawdown_percent = DecimalField(null=True)
    liquidity_after = DecimalField(null=True)
    still_tradable = BooleanField(null=True)
    benchmark_return_pct = DecimalField(null=True)


def initialize_database(path=None):
    """Create the local database and tables when persistence is enabled.

    Args:
        path: Optional database file used by tests or deployment.
    """

    database_path = Path(path) if path is not None else DATABASE_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if db.is_closed() or db.database != str(database_path):
        db.init(str(database_path))
    db.connect(reuse_if_open=True)
    db.create_tables(
        (ScanRun, TokenRecordSnapshot, GoodTokenCall, CallOutcome),
        safe=True,
    )


def close_database():
    """Close the database connection after a persistence operation."""

    if not db.is_closed():
        db.close()
    db.init(str(DATABASE_PATH))
