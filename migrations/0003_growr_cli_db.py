# Generated from a schema diff on 2026-09-24 17:47.
from peewee import *
import datetime

def up(migrator, db):
    class TokenRecordSnapshot(Model):
        class Meta:
            database = db
            table_name = 'tokenrecordsnapshot'

    class GoodTokenCall(Model):
        mint = CharField(null=True)
        snapshot_id = ForeignKeyField(TokenRecordSnapshot)
        agent_id = CharField(null=True)
        agent_version = CharField(null=True)
        strategy = CharField(null=True)
        decision = CharField(null=True)
        confidence = CharField(null=True)
        criteria = CharField(null=True)
        reasons = CharField(null=True)
        status = CharField(null=True)
        created_at = DateTimeField(default=datetime.datetime.now)
        class Meta:
            database = db
            table_name = 'goodtokencall'
    db.create_tables([GoodTokenCall])

    class CallOutcome(Model):
        call = ForeignKeyField(GoodTokenCall)
        evaluation_time = DateTimeField(default=datetime.datetime.now)
        horizon = CharField(null=True)
        price_at_decision = DecimalField(null=True)
        price_after = DecimalField(null=True)
        return_pct = DecimalField(null=True)
        max_drawdown_percent = DecimalField(null=True)
        liquidity_after = DecimalField(null=True)
        still_tradable = BooleanField(null=True)
        benchmark_return_pct = DecimalField(null=True)
        class Meta:
            database = db
            table_name = 'calloutcome'
    db.create_tables([CallOutcome])


def down(migrator, db):
    migrator.migrate(migrator.drop_table('calloutcome'))
    migrator.migrate(migrator.drop_table('goodtokencall'))
