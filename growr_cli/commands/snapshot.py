"""Read stored token snapshots from the local database."""

from growr_cli.storage import QueryManager


def get_snapshot(args, database_path=None):
    """Read the snapshot selection requested by the CLI arguments."""

    manager = QueryManager(database_path)
    if args.type == "latest":
        return manager.get_latest_record_by_mint(args.mint)
    if args.type == "single":
        return manager.get_single_record_by_id(args.snapshot_id)
    return manager.get_token_snapshots(args.mint)
