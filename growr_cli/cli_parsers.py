"""Build Growr parsers and run command-line validation."""

import argparse
import sys
from typing import NoReturn

from growr_cli import __version__
from growr_cli.cli_validators import (
    calendar_timezone,
    load_comparison,
    positive_integer,
    validate_good_call_arguments,
    validate_search_arguments,
    validate_target,
)
from growr_cli.doctor import add_doctor_parser
from growr_cli.errors import JsonArgumentError, _emit_failure
from growr_cli.history_arguments import add_history_parsers
from growr_cli.integrations.jupiter import (
    JUPITER_CATEGORIES,
    JUPITER_INTERVALS,
)
from growr_cli.integrations.stonks import STONKS_CATEGORIES, STONKS_SORTS
from growr_cli.playbook_commands import (
    add_playbook_parser,
    validate_playbook_flags,
)


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


def create_root_parser() -> argparse.ArgumentParser:
    """Create the parser containing options shared by every command."""
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
            "--json search jupiter <MINT> --store-snapshot",
            "--json search stonks te",
            "token --help",
        ),
    )

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
    return parser


def add_schema_parser(subparsers):
    """Register the offline schema command."""
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


def add_token_parser(subparsers):
    """Register the token mint scan command."""
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


def add_wallet_parser(subparsers):
    """Register the wallet scan command."""
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


def add_token_account_parser(subparsers):
    """Register the token-account scan command."""
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


def add_list_parser(subparsers):
    """Register the provider listing command."""
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
    # parsing. validate_search_arguments later checks that pagination
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
    list_parser.add_argument(
        "--store-snapshot",
        action="store_true",
        help="Persist listing observations in the local database.",
    )


def add_search_parser(subparsers) -> None:
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
    parser.add_argument(
        "--store-snapshot",
        action="store_true",
        help="Persist returned observations in the local database.",
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


def add_snapshot_parser(subparsers) -> None:
    """Register database snapshot lookup arguments."""

    parser = subparsers.add_parser(
        "snapshot",
        help="Get token snapshots from the local database.",
        description=(
            "Select all, latest, or one token snapshot by mint. "
            "These arguments describe the database lookup only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "snapshot latest --mint <MINT>",
            "snapshot all --mint <MINT>",
            "snapshot single --mint <MINT> --snapshot-id <ID>",
            "--json snapshot latest <MINT>",
        ),
    )
    parser.help_on_error = True
    parser.set_defaults(command_parser=parser)
    parser.add_argument(
        "type",
        choices=("all", "latest", "single"),
        help="Snapshot selection: all, latest, or single.",
    )
    parser.add_argument(
        "mint_positional",
        nargs="?",
        help="Token mint used to select stored snapshots.",
    )
    parser.add_argument(
        "--mint",
        dest="mint_option",
        help="Token mint used to select stored snapshots.",
    )
    parser.add_argument(
        "--snapshot-id",
        help="Database snapshot ID used with the single selection.",
    )


def add_good_call_parser(subparsers) -> None:
    """Register arguments for recording an agent token decision."""

    parser = subparsers.add_parser(
        "good-call",
        help="Record an agent's token decision.",
        description=(
            "Record a decision against a stored snapshot, or use --check "
            "to find reported calls for this mint today or yesterday. "
            "All agents sharing the database share this history. "
            "No HTTP or RPC requests are made."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_help_examples(
            "good-call <MINT> --snapshot-id <ID>",
            "--json good-call <MINT> --snapshot-id <ID>",
            "--json good-call <MINT> --check --timezone America/Mexico_City",
            "--json good-call <MINT> --snapshot-id <ID> --if-new "
            "--timezone America/Mexico_City",
        ),
    )
    parser.help_on_error = True
    parser.set_defaults(command_parser=parser)
    parser.add_argument("mint", help="Token mint for the decision.")
    parser.add_argument(
        "--snapshot-id",
        type=positive_integer,
        help="Database snapshot ID supporting the decision.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Check reported calls today/yesterday without saving a call.",
    )
    mode.add_argument(
        "--if-new",
        action="store_true",
        help="Save as reported only if this mint has no recent reported call.",
    )
    parser.add_argument(
        "--timezone",
        default="UTC",
        type=calendar_timezone,
        help="IANA timezone for calendar dates (default: UTC).",
    )
    parser.add_argument("--agent-id", help="Identifier for the agent.")
    parser.add_argument("--agent-version", help="Agent version string.")
    parser.add_argument("--strategy", help="Strategy used for the decision.")
    parser.add_argument("--decision", help="Decision made by the agent.")
    parser.add_argument("--confidence", help="Decision confidence.")
    parser.add_argument("--criteria", help="Criteria used by the strategy.")
    parser.add_argument("--reasons", help="Reasons supporting the decision.")
    parser.add_argument("--status", help="Decision status.")


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
    parser = create_root_parser()

    # This selector registers the available commands. Each add_parser()
    # below creates a subparser with its own arguments and help text.
    # dest stores the chosen command in args.scan_type; required=True
    # rejects an invocation that supplies no command.
    subparsers = parser.add_subparsers(dest="scan_type", required=True)

    add_history_parsers(subparsers)
    add_doctor_parser(subparsers)
    add_playbook_parser(subparsers)
    add_search_parser(subparsers)
    add_schema_parser(subparsers)
    add_wallet_parser(subparsers)
    add_token_account_parser(subparsers)
    add_token_parser(subparsers)
    add_list_parser(subparsers)
    add_snapshot_parser(subparsers)
    add_good_call_parser(subparsers)

    # Return the configured parser; building it does not start a scan.
    return parser


def _parse_arguments(run):
    parser = build_parser()
    try:
        args = parser.parse_args()
        if args.scan_type == "playbook":
            validate_playbook_flags(parser, sys.argv[1:])
        if args.include_raw and not args.json:
            parser.error("--include-raw requires --json")
        _normalize_snapshot_mint(parser, args)
        validate_good_call_arguments(parser, args)
        validate_search_arguments(parser, args)
        validate_target(parser, args)
        load_comparison(parser, args)
        return args
    except JsonArgumentError:
        _emit_failure(
            run,
            None,
            "INVALID_ARGUMENTS",
            "Invalid arguments; use growr.py --help",
        )
        return None


def _normalize_snapshot_mint(parser, args) -> None:
    """Accept either mint syntax and reject conflicting values."""

    if args.scan_type != "snapshot":
        return

    positional_mint = args.mint_positional
    option_mint = args.mint_option
    if positional_mint and option_mint and positional_mint != option_mint:
        parser.error("snapshot mint values must match")

    mint = option_mint or positional_mint
    if not mint:
        parser.error("snapshot requires --mint MINT")

    args.mint = mint
