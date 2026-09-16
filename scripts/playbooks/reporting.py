"""Playbook options, investigation envelopes and console output."""

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from typing import Any

from scripts.playbooks.evidence import measured_totals
from scripts.playbooks.holdings import token_amount
from scripts.playbooks.runner import valid_address

NOTES = [
    "Owner addresses may belong to pools or program authorities; they do "
    "not identify people or establish shared control.",
    "Scans run sequentially at different times, not at a single slot.",
    "Holdings are present balances, not evidence of purchases. Frozen "
    "balances may not be transferable. No USD valuation is calculated.",
    "Missing inventories or mint decimals are unknown, not zero.",
]


def bounded_integer(value, minimum, maximum) -> int:
    """Parse a limit before any child process starts."""

    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if not minimum <= result <= maximum:
        raise argparse.ArgumentTypeError(
            "must be between %s and %s" % (minimum, maximum)
        )
    return result


def address_argument(value) -> str:
    """Validate the initial target without making an RPC request."""

    if not valid_address(value):
        raise argparse.ArgumentTypeError("must be a Solana address")
    return value


def build_parser(playbook) -> argparse.ArgumentParser:
    """Explain the investigation scope and configurable call limits."""

    token = playbook == "token_holders"
    target = "MINT" if token else "WALLET"
    parser = argparse.ArgumentParser(
        prog="python3 scripts/playbooks/%s.py" % playbook,
        description=(
            "Inspect sampled token owners and their nonzero holdings."
            if token
            else "Aggregate a wallet's nonzero SPL and Token-2022 holdings."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/playbooks/%s.py <%s>\n"
            "  python3 scripts/playbooks/%s.py <%s> --json --no-jupiter\n\n"
            "Each child calls growr.py --json using this interpreter and "
            "the root .env.\n"
            "Jupiter metadata needs JUPITER_API_KEY in .env. Each batch "
            "looks up at most\n100 distinct mints in one HTTP request "
            "and makes no RPC calls. RPC fallback\n"
            "is opt-in: --mint-limit 10 permits up to 10 extra token scans. "
            "Each adds\n3-4 RPC calls; each wallet scan adds 4. "
            "No retries or recursive "
            "holder expansion."
        )
        % (playbook, target, playbook, target),
    )
    parser.add_argument("address", metavar=target, type=address_argument)
    parser.add_argument(
        "--json", action="store_true", help="Emit one playbook JSON report."
    )
    parser.add_argument(
        "--mint-limit",
        type=partial(bounded_integer, minimum=0, maximum=50),
        default=0,
        help="Additional RPC mint scans for missing units (0-50, default 0).",
    )
    parser.add_argument(
        "--no-jupiter", action="store_true", help="Skip Jupiter metadata."
    )
    parser.add_argument(
        "--jupiter-batch-limit",
        type=partial(bounded_integer, minimum=1, maximum=10),
        default=10,
        help="Jupiter batches of up to 100 mints (1-10, default 10).",
    )
    parser.add_argument(
        "--timeout",
        type=partial(bounded_integer, minimum=1, maximum=120),
        default=30,
        help="Timeout in seconds for each child (1-120, default 30).",
    )
    if token:
        parser.add_argument(
            "--wallet-limit",
            type=partial(bounded_integer, minimum=1, maximum=20),
            default=5,
            help="Sampled owners to inspect (1-20, default 5).",
        )
    return parser


def new_report(playbook, options) -> dict[str, Any]:
    """Create a playbook contract separate from Growr's scan schema."""

    return {
        "playbook_version": "1.1",
        "playbook": playbook,
        "target": options.address,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "limits": {
            "wallets": getattr(options, "wallet_limit", 1),
            "additional_mints": options.mint_limit,
            "jupiter_batches": (
                0 if options.no_jupiter else options.jupiter_batch_limit
            ),
            "child_timeout_seconds": options.timeout,
        },
        "wallets": [],
        "metadata_lookups": {},
        "error": None,
        "notes": list(NOTES),
    }


def finish_report(report, runner, resolver) -> dict[str, Any]:
    """Expose call counts, estimates and incomplete observations."""

    wallets = report["wallets"]
    incomplete = any(wallet["status"] != "success" for wallet in wallets)
    amounts_missing = any(
        holding["amount_status"] not in {"resolved", "not_requested"}
        for wallet in wallets
        for holding in wallet["holdings"] or []
    )
    metadata_missing = any(
        holding["metadata"]["status"] not in {"success", "skipped"}
        or holding["metadata_conflicts"]
        for wallet in wallets
        for holding in wallet["holdings"] or []
    )
    scans_partial = any(
        scan["status"] not in {"success", "no_data"} for scan in runner.scans
    )
    if report["status"] in {"success", "no_data"} and (
        incomplete or amounts_missing or metadata_missing or scans_partial
    ):
        report["status"] = "partial"
    report.update(
        completed_at=datetime.now(timezone.utc).isoformat(),
        scans=runner.scans,
        mint_lookups=resolver.cache,
        budget=request_budget(runner, resolver),
    )
    return report


def subprocess_limit(options) -> int:
    """Reserve separate scan and Jupiter batch allowances."""

    wallets = getattr(options, "wallet_limit", 0)
    batches = 0 if options.no_jupiter else options.jupiter_batch_limit
    return 1 + wallets + options.mint_limit + batches


def request_budget(runner, resolver) -> dict[str, Any]:
    """Distinguish child attempts from estimated network calls."""

    searches = sum(scan["command"][0] == "search" for scan in runner.scans)
    return {
        "subprocesses_attempted": len(runner.scans),
        "subprocess_limit": runner.max_calls,
        "additional_mints_attempted": resolver.lookups,
        "jupiter_batches_attempted": searches,
        "rpc_calls_upper_estimate": 4 * (len(runner.scans) - searches),
        "provider_http_requests_upper_estimate": searches,
        "measured": measured_totals(runner.scans),
        "note": "Upper estimates bound requests. Measured totals cover "
        "only children that returned validated counters.",
    }


def display(value) -> str:
    """Remove controls from provider names before terminal output."""

    return "".join(
        character for character in str(value) if character.isprintable()
    )


def display_number(value) -> str:
    """Group digits while preserving every decimal place."""

    # Decimal reads the exact quantity string without float rounding.
    return format(Decimal(value), ",f")


def display_quantity(raw, decimals) -> str:
    """Convert known units and label unresolved balances explicitly."""

    if decimals is None:
        return "%s raw units" % display_number(raw)
    return "%s tokens" % display_number(token_amount(raw, decimals))


def print_report(report, json_output) -> int:
    """Print a single machine document or a readable investigation."""

    if json_output:
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
    else:
        _print_console(report)
    return 1 if report["status"] == "error" else 0


def _print_console(report) -> None:
    """Show mint addresses, readable quantities and coverage gaps."""

    print("growr playbook | %s | %s" % (report["playbook"], report["status"]))
    print("Target: %s" % report["target"])
    if report["error"]:
        print("Error: %s" % report["error"])
    sample = report.get("sample")
    if sample:
        print(
            "Sample: %s token accounts; %s owners selected; %s unresolved"
            % (
                sample["accounts_returned"],
                len(sample["owners"]),
                len(sample["unresolved_accounts"]),
            )
        )
    for wallet in report["wallets"]:
        _print_wallet(wallet)
    budget = report["budget"]
    print(
        "\nChild commands: %s; estimated RPC calls: at most %s; "
        "Jupiter HTTP requests: at most %s"
        % (
            budget["subprocesses_attempted"],
            budget["rpc_calls_upper_estimate"],
            budget["provider_http_requests_upper_estimate"],
        )
    )
    for note in report["notes"]:
        print(display(note))


def _print_wallet(wallet) -> None:
    """Show wallet amounts alongside the earlier sampled balance."""

    print("\nWallet: %s [%s]" % (wallet["address"], wallet["status"]))
    if "sample_amount_tokens" in wallet:
        print(
            "  Target tokens in sample: %s"
            % display_number(wallet["sample_amount_tokens"])
        )
    print("  Inventory complete: %s" % wallet["inventory_complete"])
    print("  SOL balance: %s" % wallet["sol_balance"])
    if wallet["holdings"] is None:
        print("  Holdings unavailable; inspect scans in the JSON report.")
    elif not wallet["holdings"]:
        print("  No nonzero token balances in the returned inventory.")
    for holding in wallet["holdings"] or []:
        label = "target" if holding["is_target"] else "holding"
        quantity = display_quantity(holding["raw_amount"], holding["decimals"])
        if holding["decimals"] is None:
            quantity = "%s (%s)" % (quantity, holding["amount_status"])
        print("  %s %s: %s" % (label, holding["mint"], quantity))
        if holding["symbol"] or holding["name"]:
            print(
                "    %s %s"
                % (
                    display(holding["symbol"] or ""),
                    display(holding["name"] or ""),
                )
            )
        _print_metadata(holding)
        for account in holding["accounts"]:
            print(
                "    %s: %s [%s]"
                % (
                    account["address"],
                    display_quantity(
                        account["raw_amount"], holding["decimals"]
                    ),
                    account["state"],
                )
            )


def _print_metadata(holding) -> None:
    """Label metadata gaps and the source of each quantity."""

    metadata = holding["metadata"]
    print(
        "    Jupiter metadata: %s; amount source: %s"
        % (metadata["status"], holding["amount_source"] or "unknown")
    )
    if holding["metadata_conflicts"]:
        print(
            "    Metadata conflicts: %s; using RPC units"
            % ", ".join(holding["metadata_conflicts"])
        )
    if metadata.get("price_usd") is not None:
        print("    Jupiter price USD: %s" % metadata["price_usd"])
    for link in metadata.get("social", {}).get("links", []):
        print("    %s: %s" % (display(link["kind"]), display(link["url"])))
