#!/usr/bin/env python3
"""growr's read-only Python command-line scanner."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from typing import NoReturn

from solders.pubkey import Pubkey

from growr_cli import settings
from growr_cli.configuration import ConfigurationError, log_configuration
from growr_cli.enrichment import LaunchEnricher
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.integrations.stonks import StonksClient
from growr_cli.logger import configure_console_logging, get_logger
from growr_cli.machine.response import Run, build_response, serialize
from growr_cli.machine.schema import response_schema
from growr_cli.models import ScanReport, SearchReport
from growr_cli.output import renderer_for
from growr_cli.safety import redact_endpoint, safe_text
from growr_cli.scanners import (
    TokenAccountScanner,
    TokenScanner,
    WalletScanner,
)
from growr_cli.searchers import (
    STONKS_CATEGORIES,
    DexscreenerTokenSearcher,
    StonksSearcher,
)
from growr_cli.solana.rpc import RpcError, SolanaRpcClient

LOGGER = get_logger(__name__)


class JsonArgumentError(ValueError):
    """Signal invalid CLI arguments without echoing their values."""


class ArgumentParser(argparse.ArgumentParser):
    """Preserve normal help while structuring JSON argument errors."""

    help_on_error = False

    def error(self, message) -> NoReturn:
        """Keep malformed arguments out of machine output and logs."""

        if "--json" in sys.argv[1:]:
            raise JsonArgumentError("Invalid arguments; use growr.py --help")
        if self.help_on_error:
            self.print_help(sys.stderr)
            self.exit(2, f"\n{self.prog}: error: {message}\n")
        super().error(message)


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


def _help_examples(*commands) -> str:
    """Format examples and explain global option placement."""

    examples = "\n".join(
        f"  python3 growr.py {command}" for command in commands
    )
    return (
        f"Examples:\n{examples}\n\n"
        "Replace <MINT>, <WALLET>, or <TOKEN_ACCOUNT> with an address.\n"
        "Global options (--json, --include-raw, --verbose, --no-color, "
        "--rpc-url) go before the command."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for scans and discovery commands.

    Returns:
        An argument parser for the ``growr`` command.
    """

    parser = ArgumentParser(
        prog="growr",
        description=(
            "Read-only Solana token, token-account, and wallet analysis."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "token <MINT>",
            "--json wallet <WALLET>",
            "token-account <TOKEN_ACCOUNT>",
            "list stonks",
            "list dexscreener --on-chain",
            "token --help",
        ),
    )
    parser.add_argument(
        "--rpc-url",
        help=(
            "Override Helius, SOLANA_RPC_URL, CUSTOM_RPC_URL, and public "
            "RPC selection."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the versioned agent-facing JSON report.",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI terminal colors."
    )
    logging_options = parser.add_mutually_exclusive_group()
    logging_options.add_argument(
        "--verbose",
        action="store_true",
        help="Enable execution/configuration logs on stderr (default: off).",
    )
    logging_options.add_argument(
        "--quiet",
        action="store_true",
        help="Enable only warning/error logs on stderr (legacy option).",
    )

    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include fetched provider payloads; requires --json.",
    )

    subparsers = parser.add_subparsers(dest="scan_type", required=True)

    subparsers.add_parser(
        "schema",
        help="Print the JSON response schema.",
        description=(
            "Print the JSON Schema for growr's machine-readable reports. "
            "Runs offline; no address or --json flag is required."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  python3 growr.py schema > growr-schema.json",
    )

    token_parser = subparsers.add_parser(
        "token",
        help="Scan a token mint.",
        description=(
            "Inspect a Solana mint's supply, authorities, metadata and "
            "largest token accounts using RPC, with optional provider "
            "market and risk context. Pass the mint address."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "token <MINT>",
            "--json token <MINT>",
            "--json --include-raw token <MINT>",
            "token <MINT> --no-jupiter --no-rugcheck",
        ),
    )
    token_parser.add_argument("mint", help="Solana token mint address.")
    token_parser.add_argument(
        "--no-jupiter", action="store_true", help="Skip Jupiter enrichment."
    )
    token_parser.add_argument(
        "--no-rugcheck", action="store_true", help="Skip Rugcheck context."
    )

    wallet_parser = subparsers.add_parser(
        "wallet",
        help="Scan a wallet address.",
        description=(
            "Inspect a Solana wallet's SOL balance, recent signature "
            "count and SPL/Token-2022 account inventory. This is a "
            "shallow scan; it does not recursively analyze holdings "
            "or connected wallets."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "wallet <WALLET>",
            "--json wallet <WALLET>",
            "--quiet --json wallet <WALLET> > wallet-report.json",
        ),
    )
    wallet_parser.add_argument("address", help="Solana wallet address.")

    token_account_parser = subparsers.add_parser(
        "token-account",
        help="Scan an SPL token account.",
        description=(
            "Decode an SPL or Token-2022 token account and inspect its "
            "mint, owner, balance, account state and owner wallet context. "
            "Pass the token-account address, not its mint or wallet address."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "token-account <TOKEN_ACCOUNT>",
            "--json token-account <TOKEN_ACCOUNT>",
            "--no-color token-account <TOKEN_ACCOUNT>",
        ),
    )
    token_account_parser.add_argument(
        "address", help="SPL token account address."
    )

    list_parser = subparsers.add_parser(
        "list",
        help="Discover tokens from Stonks or Dexscreener.",
        description=(
            "Choose a discovery provider: stonks (recent launches by "
            "default) or dexscreener (boosted tokens by default). "
            "Dexscreener listings include only Solana tokens."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 growr.py list stonks\n"
            "  python3 growr.py list stonks --stonk-search volume\n"
            "  python3 growr.py list dexscreener --community-takeovers\n"
            "  python3 growr.py --json list dexscreener --on-chain\n\n"
            "Global options such as --json go before list.\n"
            "Legacy --stonk and Dexscreener feed selectors also work "
            "without a positional provider."
        ),
    )
    list_parser.help_on_error = True
    # Later mode validation must report the selected command's help.
    list_parser.set_defaults(command_parser=list_parser)
    list_parser.add_argument(
        "provider",
        nargs="?",
        choices=("stonks", "dexscreener", "dexcreener"),
        help="Discovery provider (dexcreener is an alias for dexscreener).",
    )
    list_parser.add_argument(
        "--boosted",
        action="store_true",
        help="Solana tokens from the latest boosts feed",
    )
    list_parser.add_argument(
        "--community-takeovers",
        action="store_true",
        help="Solana tokens from the latest community takeovers feed",
    )
    list_parser.add_argument(
        "--stonk", action="store_true", help="Stonks coins"
    )
    list_parser.add_argument(
        "--stonk-search",
        choices=("recent", "marketCap", "volume"),
        default="recent",
        help=(
            "Stonks discovery: recent launches, market cap, or volume "
            "(default: recent)."
        ),
    )
    list_parser.add_argument(
        "--category",
        choices=STONKS_CATEGORIES,
        help="Filter Stonks market-cap or volume listings by category.",
    )
    list_parser.add_argument(
        "--page",
        type=positive_integer,
        help="Platform search page (default: 1).",
    )
    list_parser.add_argument(
        "--page-size",
        type=positive_integer,
        help="Platform search page size (default: 30).",
    )
    list_parser.add_argument(
        "--on-chain",
        action="store_true",
        help="Verify Solana listing results using read-only RPC scans.",
    )

    return parser


def _validate_search_arguments(parser, args) -> None:
    """Validate discovery options for the selected mode."""

    if args.scan_type != "list":
        return

    parser = args.command_parser
    if args.provider == "stonks":
        if args.boosted or args.community_takeovers:
            parser.error("Dexscreener feed options cannot select Stonks")
        args.stonk = True
    elif args.provider is not None:
        if args.stonk:
            parser.error("--stonk conflicts with the Dexscreener provider")
        args.boosted = args.boosted or not args.community_takeovers

    if not (args.stonk or args.boosted or args.community_takeovers):
        parser.error("Missing provider: choose stonks or dexscreener")

    if args.stonk_search != "recent" and not args.stonk:
        parser.error("--stonk-search requires list stonks")

    has_pagination = args.page is not None or args.page_size is not None
    supports_platform_options = args.stonk and args.stonk_search != "recent"
    if has_pagination and not supports_platform_options:
        parser.error(
            "--page and --page-size require list stonks "
            "--stonk-search marketCap or volume"
        )
    if args.category is not None and not supports_platform_options:
        parser.error(
            "--category requires list stonks "
            "--stonk-search marketCap or volume"
        )


def _search_tokens(
    args,
    rpc_url,
    rpc_label,
    http,
) -> SearchReport:
    """Discover tokens and optionally verify Solana mints by RPC."""

    dexscreener = DexscreenerClient(http)
    jupiter = JupiterClient(http, settings.JUPITER_API_KEY)
    context = TokenContext(jupiter, dexscreener, RugcheckClient(http))

    def scan_launch(mint) -> ScanReport:
        # Each worker owns and closes its RPC connections.
        launch_rpc = SolanaRpcClient(rpc_url, settings.REQUEST_TIMEOUT_SECONDS)
        try:
            # Listing verification only requests on-chain observations.
            return TokenScanner(launch_rpc, rpc_label, context).scan(
                mint,
                include_jupiter=False,
                include_rugcheck=False,
                include_market_context=False,
            )
        finally:
            launch_rpc.close()

    if not args.stonk:
        report = DexscreenerTokenSearcher(dexscreener).search(
            boosted=args.boosted, community_takeovers=args.community_takeovers
        )
        return (
            OnChainEnricher(scan_launch).enrich(report)
            if args.on_chain
            else report
        )

    report = StonksSearcher(StonksClient(http)).search(
        args.stonk_search,
        page=args.page or 1,
        page_size=args.page_size or 30,
        category=args.category,
    )
    return LaunchEnricher(
        jupiter, dexscreener, scan_launch if args.on_chain else None
    ).enrich(report)


def _build_report(
    args,
    rpc_url,
    rpc_label,
    http,
) -> ScanReport | SearchReport:
    """Dispatch discovery or a scan and return its completed report."""

    if args.scan_type == "list":
        return _search_tokens(args, rpc_url, rpc_label, http)

    LOGGER.info("Using %s", rpc_label)
    with closing(
        SolanaRpcClient(rpc_url, settings.REQUEST_TIMEOUT_SECONDS)
    ) as rpc:
        if args.scan_type == "token":
            context = TokenContext(
                JupiterClient(http, settings.JUPITER_API_KEY),
                DexscreenerClient(http),
                RugcheckClient(http),
            )
            return TokenScanner(rpc, rpc_label, context).scan(
                args.mint,
                include_jupiter=not args.no_jupiter,
                include_rugcheck=not args.no_rugcheck,
            )
        if args.scan_type == "wallet":
            return WalletScanner(rpc, rpc_label).scan(args.address)
        return TokenAccountScanner(rpc, rpc_label).scan(args.address)


def _emit_failure(run, args, code, message) -> None:
    """Write one complete error document with a stable public code."""

    response = build_response(
        run, args, error={"code": code, "message": message}
    )
    print(serialize(response))


def _parse_arguments(run):
    parser = build_parser()
    try:
        args = parser.parse_args()
        if args.include_raw and not args.json:
            parser.error("--include-raw requires --json")
        _validate_search_arguments(parser, args)
        _validate_target(parser, args)
        return args
    except JsonArgumentError:
        _emit_failure(
            run,
            None,
            "INVALID_ARGUMENTS",
            "Invalid arguments; use growr.py --help",
        )
        return None


def _validate_target(parser, args) -> None:
    """Reject invalid addresses before constructing network clients."""

    address = getattr(args, "mint", getattr(args, "address", None))
    if address is None:
        return
    try:
        Pubkey.from_string(address)
    except ValueError:
        parser.error("Invalid Solana address")


def _log_error(args, message) -> None:
    """Keep human failures visible and default JSON free of logs."""

    message = safe_text(message)
    LOGGER.error("%s", message)
    if not (args.json or args.verbose or args.quiet):
        print(f"growr: {message}", file=sys.stderr)


def main() -> int:
    """Run a command with structured JSON failures when requested."""

    run = Run()
    args = _parse_arguments(run)
    if args is None:
        return 2
    if args.scan_type == "schema":
        print(json.dumps(response_schema(), allow_nan=False, indent=2))
        return 0
    configure_console_logging(
        use_color=not args.no_color,
        quiet=args.quiet,
        enabled=args.verbose or args.quiet,
    )
    LOGGER.info("Starting %s run", args.scan_type)
    rpc_url_override = args.rpc_url.strip() if args.rpc_url else None
    rpc_url = rpc_url_override or settings.RPC_URL
    rpc_label = (
        "CLI --rpc-url override" if rpc_url_override else settings.RPC_LABEL
    )
    with redact_endpoint(rpc_url):
        return _execute_run(args, run, rpc_url, rpc_label, rpc_url_override)


def _execute_run(args, run, rpc_url, rpc_label, rpc_url_override) -> int:
    """Execute and render within the private redaction context."""

    try:
        log_configuration(args, rpc_url, rpc_url_override)
        with closing(HttpClient(settings.REQUEST_TIMEOUT_SECONDS)) as http:
            report = _build_report(args, rpc_url, rpc_label, http)
        LOGGER.info("Rendering %s report", "JSON" if args.json else "console")
        if args.json:
            # Serialize fully before writing to stdout.
            print(serialize(build_response(run, args, report)))
        else:
            renderer_for(report, use_color=not args.no_color).render(report)
    except ConfigurationError as error:
        _log_error(args, f"Configuration failed: {error}")
        if args.json:
            _emit_failure(run, args, "EXECUTION_FAILED", str(error))
        return 1
    except (ValueError, RpcError) as error:
        code = (
            "RPC_ERROR" if isinstance(error, RpcError) else "EXECUTION_FAILED"
        )
        if args.json:
            message = (
                "RPC read failed"
                if code == "RPC_ERROR"
                else "Scan or discovery could not be completed"
            )
            _log_error(args, f"Scan failed: {message}")
            _emit_failure(run, args, code, message)
        else:
            _log_error(args, f"Scan failed: {error}")
        return 1
    except Exception as error:
        _log_error(
            args, f"Scan failed: unexpected error ({type(error).__name__})"
        )
        if args.json:
            _emit_failure(
                run, args, "INTERNAL_ERROR", "Unexpected execution failure"
            )
        return 1
    LOGGER.info("Run complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
