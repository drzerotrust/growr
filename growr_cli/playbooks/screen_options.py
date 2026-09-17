"""Screening CLI options and provider-specific discovery commands."""

import argparse
from functools import partial
from typing import Any

from growr_cli.playbooks.reporting import address_argument, bounded_integer


def build_parser() -> argparse.ArgumentParser:
    """Describe live and offline screening with explicit work bounds."""

    parser = argparse.ArgumentParser(
        prog="growr playbook token-screen",
        allow_abbrev=False,
        description="Screen Solana candidates against JSON criteria. "
        "Input files are reranked offline; live modes use Growr subprocesses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  growr playbook token-screen --criteria criteria.json "
        "--provider stonks --category xstock --json\n"
        "  growr playbook token-screen --criteria criteria.json "
        "--mints <MINT> --json\n"
        "  growr playbook token-screen --criteria criteria.json "
        "--input saved-screen.json --json\n\n"
        "Default verification requires an initialized RPC mint. "
        "Set verify_on_chain=false in criteria for provider-only screening. "
        "Missing required data remains unknown, never a verified match.",
    )
    parser.add_argument(
        "--criteria", required=True, help="Criteria 1.0 JSON file."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--provider", choices=("jupiter", "stonks"))
    source.add_argument("--mints", nargs="+", type=address_argument)
    source.add_argument(
        "--input", help="Saved discovery or screen JSON; no network."
    )
    parser.add_argument("--query", help="Name/symbol query instead of a feed.")
    parser.add_argument("--feed", help="Provider feed; defaults to recent.")
    parser.add_argument(
        "--category",
        choices=(
            "xstock",
            "prestock",
            "custom",
            "collectibles",
            "currencies",
            "leverage",
        ),
    )
    parser.add_argument("--interval", choices=("5m", "1h", "6h", "24h"))
    parser.add_argument("--sort", choices=("marketCap", "volume", "newest"))
    for name, low, high, default, help_text in (
        ("page", 1, 10000, 1, "First Stonks page."),
        ("pages", 1, 10, 1, "Maximum Stonks pages."),
        ("page-size", 1, 100, 30, "Stonks rows per page."),
        ("candidate-limit", 1, 100, 50, "Maximum distinct evaluated mints."),
        ("scan-limit", 0, 20, 5, "Maximum additional RPC token scans."),
        ("top", 1, 100, 5, "Maximum matches in the shortlist."),
        ("max-rpc-calls", 0, 500, 20, "Conservative shared RPC cap."),
        ("max-http-calls", 0, 100, 10, "Shared provider HTTP cap."),
        ("timeout", 1, 120, 30, "Seconds per child process."),
        ("max-seconds", 1, 1800, 180, "Total child execution deadline."),
    ):
        parser.add_argument(
            "--%s" % name,
            type=partial(bounded_integer, minimum=low, maximum=high),
            default=default,
            help="%s Default %s; range %s-%s."
            % (
                help_text,
                default,
                low,
                high,
            ),
        )
    parser.add_argument(
        "--json", action="store_true", help="One JSON report on stdout."
    )
    return parser


def validate_options(parser, options, argv) -> None:
    """Reject unsupported discovery options before any subprocess."""

    discovery_flags = {
        "--query",
        "--feed",
        "--category",
        "--interval",
        "--sort",
        "--page",
        "--pages",
        "--page-size",
    }
    supplied = {
        value.split("=", 1)[0] for value in argv if value.startswith("--")
    }
    if not options.provider and supplied & discovery_flags:
        parser.error("discovery options require --provider")
    if options.mints and len(options.mints) > options.candidate_limit:
        parser.error("explicit mints exceed --candidate-limit")
    if options.query is not None:
        options.query = options.query.strip()
        if (
            not options.query
            or len(options.query) > 256
            or options.query.startswith("-")
        ):
            parser.error("query must be nonblank text, at most 256 characters")
        if supplied & {"--feed", "--category", "--interval"}:
            parser.error("query search does not accept feed/category/interval")
    validate_provider_options(parser, options, supplied)


def validate_provider_options(parser, options, supplied) -> None:
    """Check flags specific to the selected provider."""

    if options.provider == "jupiter":
        if supplied & {
            "--sort",
            "--category",
            "--page",
            "--pages",
            "--page-size",
        }:
            parser.error("Jupiter does not accept Stonks discovery options")
        if options.feed not in (
            None,
            "recent",
            "toptraded",
            "toptrending",
            "toporganicscore",
        ):
            parser.error("invalid Jupiter feed")
        if options.interval and options.feed in (None, "recent"):
            parser.error("--interval requires a ranked Jupiter feed")
    if options.provider == "stonks":
        if options.feed not in (None, "recent", "marketCap", "volume"):
            parser.error("invalid Stonks feed")
        if options.interval or (options.sort and options.query is None):
            parser.error(
                "Stonks accepts --sort only for queries and no interval"
            )


def discovery_command(options, page) -> tuple[list[str], dict[str, Any]]:
    """Build allowlisted arguments and the expected report scope."""

    source = options.provider
    mode = options.feed or "recent"
    command = ["list", source]
    expected = {"source": source, "mode": mode, "on_chain": False}
    if options.query is not None:
        command = ["search", source, options.query]
        expected = {"source": source, "mode": "search", "query": options.query}
    if source == "stonks":
        command.extend(
            ["--page", str(page), "--page-size", str(options.page_size)]
        )
        expected.update(page=page, page_size=options.page_size)
        if options.query is not None:
            command.extend(["--sort", options.sort or "marketCap"])
            expected["sort"] = options.sort or "marketCap"
        else:
            command.extend(["--stonk-search", mode])
            expected["category"] = options.category
            if options.category:
                command.extend(["--category", options.category])
    elif options.query is None:
        command.extend(["--jupiter-search", mode])
        if mode != "recent":
            command.extend(
                [
                    "--interval",
                    options.interval or "24h",
                    "--limit",
                    str(options.candidate_limit),
                ]
            )
            expected.update(
                interval=options.interval or "24h",
                limit=options.candidate_limit,
            )
    return command, expected
