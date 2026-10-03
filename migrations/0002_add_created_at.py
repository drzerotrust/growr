# Generated from a schema diff on 2026-09-23 21:47.
from peewee import *
import datetime

def up(migrator, db):
    migrator.migrate(migrator.add_column('tokenrecordsnapshot', 'created_at', DateTimeField(default=datetime.datetime.now)))


def down(migrator, db):
    migrator.migrate(migrator.drop_column('tokenrecordsnapshot', 'created_at'))
