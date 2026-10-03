# Generated from a schema diff on 2026-09-23 21:38.
from peewee import *
from playhouse.sqlite_ext import JSONField
import datetime

def up(migrator, db):
    class ScanRun(Model):
        id = UUIDField(primary_key=True)
        started_at = DateTimeField()
        completed_at = DateTimeField(null=True)
        command = TextField()
        arguments = JSONField()
        filters = JSONField(null=True)
        provider = CharField(null=True, max_length=64)
        code_version = CharField(null=True, max_length=64)
        status = CharField(max_length=32)
        class Meta:
            database = db
            table_name = 'scanrun'
    db.create_tables([ScanRun])

    class TokenRecordSnapshot(Model):
        run = ForeignKeyField(ScanRun)
        observed_at = DateTimeField(index=True)
        provider = CharField(index=True, max_length=64)
        query_fingerprint = CharField(index=True, null=True, max_length=64)
        code_version = CharField(null=True, max_length=64)
        source_timestamp = DateTimeField(null=True)
        kind = CharField(null=True, max_length=64)
        chain = CharField(null=True, max_length=32)
        mint = CharField(index=True, max_length=64)
        pool = CharField(null=True, max_length=64)
        name = CharField(null=True)
        symbol = CharField(null=True, max_length=64)
        launch_status = CharField(null=True, max_length=64)
        token_created_at = DateTimeField(null=True)
        graduated_at = DateTimeField(null=True)
        creator = CharField(null=True, max_length=64)
        launchpad = CharField(null=True, max_length=64)
        quote_mint = CharField(null=True, max_length=64)
        quote_name = CharField(null=True)
        quote_symbol = CharField(null=True, max_length=64)
        quote_category = CharField(null=True, max_length=64)
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
        holder_count = IntegerField(null=True)
        token_dev = CharField(null=True, max_length=64)
        organic_score = DecimalField(null=True)
        organic_score_label = CharField(null=True, max_length=64)
        is_verified = BooleanField(null=True)
        token_program = CharField(null=True, max_length=64)
        total_supply = DecimalField(null=True)
        circulating_supply = DecimalField(null=True)
        mint_disabled = BooleanField(null=True)
        freeze_authority_disabled = BooleanField(null=True)
        top_holders_percentage = DecimalField(null=True)
        dev_balance_percentage = DecimalField(null=True)
        dev_migrations = IntegerField(null=True)
        dev_mints = IntegerField(null=True)
        transfer_tax_bps = DecimalField(null=True)
        activity_snapshot = JSONField(null=True)
        social_score = IntegerField(null=True)
        has_website = BooleanField(null=True)
        social_links = JSONField(null=True)
        coverage = JSONField(null=True)
        screen_eligible = BooleanField(null=True)
        screen_score = DecimalField(null=True)
        screen_rank = IntegerField(null=True)
        rejection_reasons = JSONField(null=True)
        created_at = DateTimeField(default=datetime.datetime.now)
        class Meta:
            database = db
            table_name = 'tokenrecordsnapshot'
    db.create_tables([TokenRecordSnapshot])


def down(migrator, db):
    migrator.migrate(migrator.drop_table('tokenrecordsnapshot'))
    migrator.migrate(migrator.drop_table('scanrun'))
