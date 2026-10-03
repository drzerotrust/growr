"""Argument validators for Growr command-line workflows."""

import argparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from solders.pubkey import Pubkey

from growr_cli.integrations.jupiter import (
    JUPITER_CATEGORIES,
    discovery_request,
)
from growr_cli.integrations.stonks import (
    listing_parameters as stonks_listing_parameters,
)
from growr_cli.integrations.stonks import (
    query_parameters as stonks_query_parameters,
)
from growr_cli.machine.comparison import load_reward_snapshot


def positive_integer(value) -> int:
    """Parse a positive pagination argument."""

    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "must be a positive integer"
        ) from None
    if result < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def calendar_timezone(value) -> str:
    """Validate an IANA timezone before any database work."""

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise argparse.ArgumentTypeError(
            "must be an IANA timezone, such as UTC or America/Mexico_City"
        ) from None
    return value


def validate_good_call_arguments(parser, args) -> None:
    """Separate the read-only check from recording a decision."""

    if args.scan_type != "good-call":
        return
    parser = args.command_parser
    if not args.check and args.snapshot_id is None:
        parser.error("recording a good-call requires --snapshot-id")
    if args.check:
        write_values = (
            args.snapshot_id,
            args.agent_id,
            args.agent_version,
            args.strategy,
            args.decision,
            args.confidence,
            args.criteria,
            args.reasons,
            args.status,
        )
        if any(value is not None for value in write_values):
            parser.error("--check cannot include decision or snapshot fields")
    if args.if_new and args.status not in {None, "reported"}:
        parser.error("--if-new records --status reported")


def validate_search_arguments(parser, args) -> None:
    """Validate feed or query options before creating clients."""

    if args.scan_type == "search":
        validate_query_arguments(args.command_parser, args)
    elif args.scan_type == "list":
        validate_listing_arguments(args.command_parser, args)


def validate_query_arguments(parser, args) -> None:
    """Normalize a query using the integration's endpoint contract."""

    if args.provider == "stonks":
        validate_stonks_query_arguments(parser, args)
        return
    if any(
        value is not None for value in (args.sort, args.page, args.page_size)
    ):
        parser.error("--sort, --page and --page-size require search stonks")
    try:
        _, params = discovery_request("search", args.query, None, None)
    except ValueError as error:
        parser.error(str(error))
    args.query = params["query"]


def validate_stonks_query_arguments(parser, args) -> None:
    """Apply Stonks query defaults at the CLI boundary."""

    try:
        params = stonks_query_parameters(
            args.query, args.sort, args.page, args.page_size
        )
    except ValueError as error:
        parser.error(str(error))
    args.query = params["q"]
    args.sort = params["sort"]
    args.page = params["page"]
    args.page_size = params["pageSize"]


def validate_listing_arguments(parser, args) -> None:
    """Keep feed options limited to their selected provider."""

    if args.provider == "stonks":
        args.stonk = True
    elif args.provider == "jupiter" and args.stonk:
        parser.error("--stonk conflicts with the Jupiter provider")
    if args.provider is None and not args.stonk:
        parser.error("Missing provider: choose stonks or jupiter")
    args.provider = "stonks" if args.stonk else "jupiter"
    validate_jupiter_arguments(parser, args)

    if args.stonk_search is not None and not args.stonk:
        parser.error("--stonk-search requires list stonks")
    args.stonk_search = args.stonk_search or "recent"

    has_pagination = args.page is not None or args.page_size is not None
    if (has_pagination or args.category is not None) and not args.stonk:
        parser.error("--page, --page-size and --category require list stonks")
    if args.stonk:
        sort = "newest" if args.stonk_search == "recent" else args.stonk_search
        try:
            stonks_listing_parameters(
                sort, args.page or 1, args.page_size or 30, args.category
            )
        except ValueError as error:
            parser.error(str(error))


def validate_jupiter_arguments(parser, args) -> None:
    """Keep provider options separate and apply documented defaults."""

    if args.stonk:
        unsupported = []
        if args.jupiter_search is not None:
            unsupported.append(
                "--jupiter-search (use --stonk-search for Stonks feeds)"
            )
        if args.interval is not None:
            unsupported.append(
                "--interval (Stonks listings do not have Jupiter intervals)"
            )
        if args.limit is not None:
            unsupported.append(
                "--limit (use --page-size for Stonks result count)"
            )
        if unsupported:
            parser.error(
                "Stonks does not support %s; choose a Stonks option "
                "instead" % ", ".join(unsupported)
            )
        return
    mode = args.jupiter_search or "recent"
    try:
        discovery_request(mode, None, args.interval, args.limit)
    except ValueError as error:
        parser.error(str(error))
    args.jupiter_search = mode
    if mode in JUPITER_CATEGORIES:
        args.interval = args.interval or "24h"
        args.limit = args.limit or 50


def load_comparison(parser, args) -> None:
    """Read a comparison report before any network clients exist."""

    filename = getattr(args, "compare_to", None)
    if filename is None:
        return
    if not args.stonk:
        parser.error("--compare-to requires token --stonk")
    try:
        args.reward_snapshot = load_reward_snapshot(filename, args.mint)
    except ValueError as error:
        parser.error(str(error))


def validate_target(parser, args) -> None:
    """Reject invalid addresses before constructing network clients."""

    address = getattr(args, "mint", getattr(args, "address", None))
    if address is None:
        return
    try:
        Pubkey.from_string(address)
    except ValueError:
        parser.error("Invalid Solana address")
