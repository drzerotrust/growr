#!/usr/bin/env python3
"""growr's read-only Python command-line scanner."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from typing import NoReturn

from solders.pubkey import Pubkey

from growr_cli import __version__, settings
from growr_cli.configuration import ConfigurationError, log_configuration
from growr_cli.doctor import add_doctor_parser, run_doctor
from growr_cli.enrichment import LaunchEnricher
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.enrichment.stonks_token import StonksTokenContext
from growr_cli.enrichment.token_context import TokenContext
from growr_cli.history_arguments import add_history_parsers
from growr_cli.integrations.http import HttpClient, ProviderError
from growr_cli.integrations.jupiter import (
    JUPITER_CATEGORIES,
    JUPITER_INTERVALS,
    JupiterClient,
    discovery_request,
)
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.integrations.stonks import (
    STONKS_SORTS,
    StonksClient,
)
from growr_cli.integrations.stonks import (
    listing_parameters as stonks_listing_parameters,
)
from growr_cli.integrations.stonks import (
    query_parameters as stonks_query_parameters,
)
from growr_cli.integrations.stonks_token import StonksTokenClient
from growr_cli.logger import configure_console_logging, get_logger
from growr_cli.machine.comparison import load_reward_snapshot
from growr_cli.machine.response import Run, build_response, serialize
from growr_cli.machine.schema import response_schema
from growr_cli.models import ScanReport, SearchReport
from growr_cli.output import renderer_for
from growr_cli.playbook_commands import (
    add_playbook_parser,
    run_playbook,
    validate_playbook_flags,
)
from growr_cli.requests import RequestBudget
from growr_cli.safety import redact_endpoint, safe_text
from growr_cli.scanners import (
    TokenAccountScanner,
    TokenScanner,
    WalletScanner,
)
from growr_cli.scanners.history import HistoryScanner
from growr_cli.searchers import (
    STONKS_CATEGORIES,
    JupiterTokenSearcher,
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
            self.exit(2, "\n%s: error: %s\n" % (self.prog, message))
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
        "  python3 growr.py %s" % command for command in commands
    )
    return (
        "Examples:\n%s\n\nReplace <MINT>, <WALLET>, or <TOKEN_ACCOUNT> "
        "with an address.\nGlobal options (--json, --include-raw, "
        "--verbose, --no-color, --rpc-url) go before the command."
    ) % examples


def build_parser() -> argparse.ArgumentParser:
    """Define the CLI commands, accepted arguments and help text.

    The main parser owns shared options such as --json. A subparser
    is a parser for one command: token accepts a mint and provider
    flags, while wallet accepts a wallet address. Choosing a command
    selects the subparser that reads the remaining arguments.

    This function only registers those rules. Later, _parse_arguments
    calls parse_args() to read the command line into a Namespace object,
    accessed as args.json, args.mint and similar attributes.
    _build_report then uses those values to run the selected workflow.

    Returns:
        An argument parser for the ``growr`` command.
    """

    # prog controls the name printed in help and errors. The formatter
    # preserves line breaks in the description and epilog examples.
    parser = ArgumentParser(
        prog="growr",
        description=(
            "Read-only Solana token, token-account, and wallet analysis."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "token <MINT>",
            "token <MINT> --stonk",
            "--json wallet <WALLET>",
            "token-account <TOKEN_ACCOUNT>",
            "list stonks",
            "list jupiter --on-chain",
            "--json search jupiter JUP",
            "--json search stonks te",
            "token --help",
        ),
    )

    # Main-parser options go before the command: --json token <MINT>.
    # --rpc-url takes a value; store_true flags default to False and
    # become True when supplied. Hyphens become underscores in attribute
    # names, such as args.rpc_url.
    parser.add_argument(
        "--version", action="version", version="growr %s" % __version__
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
        "--commitment",
        choices=("finalized", "confirmed"),
        default="finalized",
        help="RPC observation commitment (default: finalized).",
    )
    parser.add_argument(
        "--max-rpc-calls",
        type=positive_integer,
        default=500,
        help="Hard RPC attempt cap across this run (default: 500).",
    )
    parser.add_argument(
        "--max-http-calls",
        type=positive_integer,
        default=100,
        help="Hard provider HTTP attempt cap (default: 100).",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI terminal colors."
    )

    # Neither logging flag is required, but argparse rejects using both.
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

    # The dependency on --json is checked later in _parse_arguments.
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include fetched provider payloads; requires --json.",
    )

    # This selector registers the available commands. Each add_parser()
    # below creates a subparser with its own arguments and help text.
    # dest stores the chosen command in args.scan_type; required=True
    # rejects an invocation that supplies no command.
    subparsers = parser.add_subparsers(dest="scan_type", required=True)
    add_history_parsers(subparsers)
    add_doctor_parser(subparsers)
    add_playbook_parser(subparsers)

    # schema needs no address or provider options. Its handler later
    # prints the JSON contract without opening network connections.
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

    # token requires a mint positional argument. Provider options such
    # as --stonk follow the command and select its external context.
    token_parser = subparsers.add_parser(
        "token",
        help="Scan a token mint.",
        description=(
            "Inspect a Solana mint's supply, authorities, metadata and "
            "largest token accounts using RPC, with optional provider "
            "market and risk context. Pass the mint address. "
            "Use --stonk for Stonkfun market, holder, burn and reward data."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "token <MINT>",
            "--json token <MINT>",
            "--json --include-raw token <MINT>",
            "token <MINT> --stonk",
            "--json token <MINT> --stonk",
            "--json token <MINT> --stonk > first.json",
            "--json token <MINT> --stonk "
            "--compare-to first.json > latest.json",
            "token <MINT> --no-jupiter --no-rugcheck",
        ),
    )
    token_parser.add_argument("mint", help="Solana token mint address.")
    token_parser.add_argument(
        "--stonk",
        action="store_true",
        help=(
            "Use Stonkfun context instead of Jupiter and "
            "Rugcheck; retain RPC checks."
        ),
    )
    token_parser.add_argument(
        "--compare-to",
        metavar="REPORT.json",
        help=(
            "Compare Stonks reward totals with a previous Growr JSON report; "
            "requires --stonk. Use a different file for redirected output."
        ),
    )
    token_parser.add_argument(
        "--no-jupiter", action="store_true", help="Skip Jupiter enrichment."
    )
    token_parser.add_argument(
        "--no-rugcheck", action="store_true", help="Skip Rugcheck context."
    )

    # Wallet options are declared independently of token options, so
    # a token-only flag such as --stonk is rejected for wallet scans.
    wallet_parser = subparsers.add_parser(
        "wallet",
        help="Scan a wallet address.",
        description=(
            "Inspect a Solana wallet's SOL balance, recent signature "
            "count and SPL/Token-2022 account inventory, including "
            "account addresses, mints, raw balances and states. This is a "
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

    # This address is a token account, distinct from its mint or wallet.
    # Parsing collects the text; the scanner checks the account type.
    token_account_parser = subparsers.add_parser(
        "token-account",
        help="Scan an SPL Token or Token-2022 token account.",
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
        "address", help="SPL Token or Token-2022 token-account address."
    )

    # Search returns query candidates for a later token scan.
    # Its parser deliberately exposes no RPC verification options.
    _add_search_parser(subparsers)

    # list has one subparser for both discovery providers. The provider
    # is a positional value within list, not another nested subcommand.
    list_parser = subparsers.add_parser(
        "list",
        help="Discover Solana tokens from Stonks or Jupiter.",
        description=(
            "Choose a discovery provider: stonks (newest tokens by "
            "default) or jupiter (recent pools by default). "
            "Jupiter also supports ranked trading feeds. "
            "Use search jupiter <QUERY> to find a name, symbol or mint."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 growr.py list stonks\n"
            "  python3 growr.py list stonks --stonk-search volume\n"
            "  python3 growr.py list jupiter\n"
            "  python3 growr.py list jupiter --jupiter-search toptraded "
            "--interval 1h --limit 20\n"
            "  python3 growr.py --json list jupiter --on-chain\n\n"
            "Global options such as --json go before list.\n"
            "Legacy --stonk also works "
            "without a positional provider."
        ),
    )
    # This is our ArgumentParser subclass's behavior: show the complete
    # list help on human-readable errors, including a missing provider.
    list_parser.help_on_error = True
    # Later mode validation must report the selected command's help.
    list_parser.set_defaults(command_parser=list_parser)

    # nargs="?" allows the provider to be omitted for legacy selectors
    # such as list --stonk. choices restricts supplied values; later
    # validation requires a provider or selector and rejects conflicts.
    list_parser.add_argument(
        "provider",
        nargs="?",
        choices=("stonks", "jupiter"),
        help="Discovery provider.",
    )

    # These options select Jupiter discovery. Provider-specific
    # validation below rejects combinations with Stonks options.
    list_parser.add_argument(
        "--jupiter-search",
        choices=("recent", *JUPITER_CATEGORIES),
        help="Jupiter feed (default: recent).",
    )
    list_parser.add_argument(
        "--interval",
        choices=JUPITER_INTERVALS,
        help="Jupiter ranked-feed interval (default: 24h).",
    )
    list_parser.add_argument(
        "--limit",
        type=positive_integer,
        help="Jupiter ranked-feed size, 1–100 (default: 50).",
    )
    list_parser.add_argument(
        "--stonk", action="store_true", help="Stonks coins"
    )

    # Leave the mode unset here so later validation can distinguish an
    # explicit --stonk-search from the implicit recent-launch default.
    list_parser.add_argument(
        "--stonk-search",
        choices=("recent", "marketCap", "volume"),
        help=(
            "Stonks discovery: newest tokens, market cap, or volume "
            "(default: recent)."
        ),
    )
    list_parser.add_argument(
        "--category",
        choices=STONKS_CATEGORIES,
        help="Filter Stonks listings by quote category.",
    )

    # type converts command-line text and rejects invalid numbers during
    # parsing. _validate_search_arguments later checks that pagination
    # and category are used with a supported Stonks search mode.
    list_parser.add_argument(
        "--page",
        type=positive_integer,
        help="Platform search page (default: 1).",
    )
    list_parser.add_argument(
        "--page-size",
        type=positive_integer,
        help="Stonks results per page, 1–100 (default: 30).",
    )

    # Both listing providers can request additional RPC verification.
    list_parser.add_argument(
        "--on-chain",
        action="store_true",
        help="Verify Solana listing results using read-only RPC scans.",
    )

    # Return the configured parser; building it does not start a scan.
    return parser


def _add_search_parser(subparsers) -> None:
    """Register query discovery separately from feeds and RPC scans."""

    parser = subparsers.add_parser(
        "search",
        help="Find Solana token candidates by name, symbol or mint.",
        description=(
            "Search Jupiter or Stonks for token candidates and available "
            "market/social information. Jupiter requires JUPITER_API_KEY; "
            "Stonks needs no API key. "
            "Makes one provider lookup without RPC calls. "
            "Select a returned mint and use token <MINT> for analysis."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "search jupiter JUP",
            'search jupiter "Jupiter"',
            "search jupiter <MINT>",
            "--json search jupiter JUP",
            "--json --include-raw search jupiter <MINT>",
            "search stonks te",
            "search stonks te --sort volume --page 2 --page-size 30",
            "--json search stonks te",
            "--json token <MINT>",
            "--json token <MINT> --stonk",
        ),
    )
    parser.help_on_error = True
    parser.set_defaults(command_parser=parser)
    parser.add_argument(
        "provider", choices=("jupiter", "stonks"), help="Search provider."
    )
    parser.add_argument(
        "query",
        metavar="QUERY",
        help=(
            "Search text; quote queries containing spaces. "
            "Jupiter also accepts up to 100 comma-separated mint addresses."
        ),
    )
    stonks_options = parser.add_argument_group("Stonks search options")
    stonks_options.add_argument(
        "--sort",
        choices=STONKS_SORTS,
        help="Pool ranking (default: marketCap).",
    )
    stonks_options.add_argument(
        "--page", type=positive_integer, help="Result page (default: 1)."
    )
    stonks_options.add_argument(
        "--page-size",
        type=positive_integer,
        help="Results per page, 1–100 (default: 30).",
    )


def _validate_search_arguments(parser, args) -> None:
    """Validate feed or query options before creating clients."""

    if args.scan_type == "search":
        _validate_query_arguments(args.command_parser, args)
    elif args.scan_type == "list":
        _validate_listing_arguments(args.command_parser, args)


def _validate_query_arguments(parser, args) -> None:
    """Normalize a query using the integration's endpoint contract."""

    if args.provider == "stonks":
        _validate_stonks_query_arguments(parser, args)
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


def _validate_stonks_query_arguments(parser, args) -> None:
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


def _validate_listing_arguments(parser, args) -> None:
    """Keep feed options limited to their selected provider."""

    if args.provider == "stonks":
        args.stonk = True
    elif args.provider == "jupiter" and args.stonk:
        parser.error("--stonk conflicts with the Jupiter provider")
    if args.provider is None and not args.stonk:
        parser.error("Missing provider: choose stonks or jupiter")
    args.provider = "stonks" if args.stonk else "jupiter"
    _validate_jupiter_arguments(parser, args)

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


def _validate_jupiter_arguments(parser, args) -> None:
    """Keep provider options separate and apply documented defaults."""

    if args.stonk:
        if any(
            value is not None
            for value in (
                args.jupiter_search,
                args.interval,
                args.limit,
            )
        ):
            parser.error("Jupiter search options require list jupiter")
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


def _search_tokens(args, http) -> SearchReport:
    """Query one provider without constructing scan dependencies."""

    if args.provider == "stonks":
        return StonksSearcher(StonksClient(http)).search_query(
            args.query,
            sort=args.sort,
            page=args.page,
            page_size=args.page_size,
        )

    jupiter = JupiterClient(http, settings.JUPITER_API_KEY)
    return JupiterTokenSearcher(jupiter).search("search", query=args.query)


def _list_tokens(
    args,
    rpc_url,
    rpc_label,
    http,
) -> SearchReport:
    """Discover tokens and optionally verify Solana mints by RPC."""

    jupiter = JupiterClient(http, settings.JUPITER_API_KEY)
    context = TokenContext(jupiter, RugcheckClient(http))

    def scan_launch(mint) -> ScanReport:
        # Each worker owns and closes its RPC connections.
        launch_rpc = SolanaRpcClient(
            rpc_url,
            settings.REQUEST_TIMEOUT_SECONDS,
            commitment=args.commitment,
            budget=http.budget,
        )
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
        report = JupiterTokenSearcher(jupiter).search(
            args.jupiter_search,
            interval=args.interval,
            limit=args.limit,
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
        jupiter, scan_launch if args.on_chain else None
    ).enrich(report)


def _token_context(args, http) -> TokenContext | StonksTokenContext:
    """Select context providers at the composition boundary."""

    if args.stonk:
        return StonksTokenContext(
            StonksTokenClient(http), getattr(args, "reward_snapshot", None)
        )
    return TokenContext(
        JupiterClient(http, settings.JUPITER_API_KEY),
        RugcheckClient(http),
    )


def _build_report(
    args,
    rpc_url,
    rpc_label,
    http,
) -> ScanReport | SearchReport:
    """Dispatch discovery or a scan and return its completed report."""

    if args.scan_type == "search":
        return _search_tokens(args, http)
    if args.scan_type == "list":
        return _list_tokens(args, rpc_url, rpc_label, http)

    LOGGER.info("Using %s", rpc_label)
    with closing(
        SolanaRpcClient(
            rpc_url,
            settings.REQUEST_TIMEOUT_SECONDS,
            commitment=args.commitment,
            budget=http.budget,
        )
    ) as rpc:
        if args.scan_type == "transaction":
            return HistoryScanner(rpc, rpc_label).transaction(args.signature)
        if args.scan_type == "history":
            return HistoryScanner(rpc, rpc_label).history(
                args.address, args.limit, args.before, args.until, args.details
            )
        if args.scan_type == "token":
            context = _token_context(args, http)
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
        if args.scan_type == "playbook":
            validate_playbook_flags(parser, sys.argv[1:])
        if args.include_raw and not args.json:
            parser.error("--include-raw requires --json")
        _validate_search_arguments(parser, args)
        _validate_target(parser, args)
        _load_comparison(parser, args)
        return args
    except JsonArgumentError:
        _emit_failure(
            run,
            None,
            "INVALID_ARGUMENTS",
            "Invalid arguments; use growr.py --help",
        )
        return None


def _load_comparison(parser, args) -> None:
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
        print("growr: %s" % message, file=sys.stderr)


def main() -> int:
    """Run a command with structured JSON failures when requested."""

    run = Run()
    args = _parse_arguments(run)
    if args is None:
        return 2
    if args.scan_type == "doctor":
        return run_doctor(args)
    if args.scan_type == "playbook":
        return run_playbook(args)
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

    run.budget = RequestBudget(args.max_rpc_calls, args.max_http_calls)
    try:
        log_configuration(args, rpc_url, rpc_url_override)
        with closing(
            HttpClient(settings.REQUEST_TIMEOUT_SECONDS, run.budget)
        ) as http:
            report = _build_report(args, rpc_url, rpc_label, http)
        requests = run.budget.snapshot()
        LOGGER.info(
            "Requests attempted: %s RPC, %s provider HTTP",
            requests["rpc"]["attempted"],
            requests["http"]["attempted"],
        )
        LOGGER.info("Rendering %s report", "JSON" if args.json else "console")
        if args.json:
            # Serialize fully before writing to stdout.
            print(serialize(build_response(run, args, report)))
        else:
            renderer_for(report, use_color=not args.no_color).render(report)
    except ConfigurationError as error:
        _log_error(args, "Configuration failed: %s" % error)
        if args.json:
            _emit_failure(run, args, "EXECUTION_FAILED", str(error))
        return 1
    except ProviderError as error:
        # Safe transport details retain API codes and Retry-After for
        # scheduled callers. Arbitrary ValueError text stays concealed.
        _log_error(args, "Run failed: %s" % error)
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
            _log_error(args, "Run failed: %s" % message)
            _emit_failure(run, args, code, message)
        else:
            _log_error(args, "Run failed: %s" % error)
        return 1
    except Exception as error:
        _log_error(
            args, "Run failed: unexpected error (%s)" % type(error).__name__
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
