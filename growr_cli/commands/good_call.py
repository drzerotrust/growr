"""Check recent recommendations and save agent decisions."""

from growr_cli.storage import GoodCallManager


def run_good_call(args, database_path=None):
    """Check or record a mint using the selected calendar timezone."""

    manager = GoodCallManager(database_path)
    if args.check:
        return manager.check_good_call(args.mint, args.timezone)

    values = {"mint": args.mint, "snapshot_id": args.snapshot_id}
    for field in (
        "agent_id",
        "agent_version",
        "strategy",
        "decision",
        "confidence",
        "criteria",
        "reasons",
        "status",
    ):
        values[field] = getattr(args, field)

    return manager.record_good_call(
        values,
        if_new=args.if_new,
        timezone_name=args.timezone,
    )
