"""Inspect bounded address activity using Growr subprocesses only."""

import argparse
import json
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.playbooks.evidence import measured_totals
from scripts.playbooks.reporting import (
    address_argument,
    bounded_integer,
    display,
)
from scripts.playbooks.runner import GrowrRunner


def build_parser() -> argparse.ArgumentParser:
    """Describe account scope and hard investigation limits."""

    parser = argparse.ArgumentParser(
        description="Read address histories, deduplicate signatures, then "
        "inspect transactions. No automatic token-account discovery.",
        epilog="Example: python3 scripts/playbooks/activity.py <WALLET> "
        "--token-account <ACCOUNT> --limit 10 --json",
    )
    parser.add_argument("address", type=address_argument)
    parser.add_argument(
        "--token-account",
        action="append",
        default=[],
        type=address_argument,
        help="Additional address to inspect (repeat up to 10 times).",
    )
    for flag, maximum, default, help_text in (
        ("limit", 100, 10, "Signatures per address page."),
        ("pages", 10, 1, "Maximum pages per address."),
        ("transactions", 100, 20, "Maximum unique transaction bodies."),
        (
            "max-rpc-calls",
            500,
            50,
            "Hard shared cap; each child makes one RPC attempt.",
        ),
        ("timeout", 120, 30, "Seconds allowed per child."),
    ):
        parser.add_argument(
            "--%s" % flag,
            type=partial(bounded_integer, minimum=1, maximum=maximum),
            default=default,
            help="%s Default: %s; maximum: %s."
            % (help_text, default, maximum),
        )
    parser.add_argument("--json", action="store_true")
    return parser


def read_pages(
    address, options, runner
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retain per-address continuation when a bound stops pagination."""

    references = []
    cursors = set()
    before = None
    outcome = {
        "address": address,
        "pages": [],
        "next_before": None,
        "stop_reason": "page_limit",
    }
    for _ in range(options.pages):
        if len(runner.scans) >= runner.max_calls:
            outcome["stop_reason"] = "request_budget"
            break
        record = runner.history(address, options.limit, before)
        if record is None:
            outcome["stop_reason"] = "history_failed"
            break
        facts = record["facts"]
        for entry in facts["entries"]:
            references.append(
                {
                    "signature": entry["signature"],
                    "address": address,
                    "scan_index": len(runner.scans) - 1,
                    "slot": entry["slot"],
                }
            )
        page = facts["pagination"]
        outcome["pages"].append(page)
        cursor = page["next_before"]
        if cursor in cursors:
            outcome["stop_reason"] = "cursor_not_advancing"
            break
        outcome["next_before"] = cursor
        if cursor is None:
            outcome["stop_reason"] = "provider_page_exhausted"
            break
        cursors.add(cursor)
        before = cursor
    return outcome, references


def investigate(options, runner) -> dict[str, Any]:
    """Collect references, then spend the body budget once per ID."""

    started = datetime.now(timezone.utc).isoformat()
    addresses = list(dict.fromkeys([options.address, *options.token_account]))
    signatures = {}
    windows = []
    for address in addresses:
        window, references = read_pages(address, options, runner)
        windows.append(window)
        for reference in references:
            signature = reference["signature"]
            if signature not in signatures:
                signatures[signature] = {
                    "signature": signature,
                    "references": [],
                    "transaction": None,
                    "detail_status": "not_requested",
                }
            signatures[signature]["references"].append(reference)
    for index, item in enumerate(signatures.values()):
        if (
            index >= options.transactions
            or len(runner.scans) >= runner.max_calls
        ):
            item["detail_status"] = "budget_exhausted"
            continue
        record = runner.transaction(item["signature"])
        item["detail_status"] = "failed"
        if record is not None:
            item["transaction"] = record["facts"]["transaction"]
            item["detail_status"] = runner.scans[-1]["status"]
    partial = any(
        row["detail_status"] != "success" for row in signatures.values()
    )
    partial = partial or any(
        row["stop_reason"] not in {"page_limit", "provider_page_exhausted"}
        for row in windows
    )
    status = "partial" if partial else "success"
    if not signatures and all(not row["pages"] for row in windows):
        status = "error"
    return {
        "playbook_version": "1.1",
        "playbook": "activity",
        "target": options.address,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "scope": "explicit_address_references",
        "windows": windows,
        "transactions": list(signatures.values()),
        "scans": runner.scans,
        "budget": {
            "measured": measured_totals(runner.scans),
            "rpc_calls_upper_estimate": len(runner.scans),
            "rpc_limit": options.max_rpc_calls,
            "unique_body_limit": options.transactions,
        },
        "notes": [
            "Address references can miss other or closed token accounts.",
            "Balances are not proof of purchases; shared activity "
            "is not shared control.",
            "No lifetime completeness, bundle membership or PnL is inferred.",
        ],
    }


def main(argv=None) -> int:
    """Run a bounded activity investigation and emit one report."""

    parser = build_parser()
    options = parser.parse_args(argv)
    if len(options.token_account) > 10:
        parser.error("at most 10 additional token-account addresses")
    runner = GrowrRunner(options.timeout, options.max_rpc_calls)
    report = investigate(options, runner)
    if options.json:
        print(json.dumps(report, allow_nan=False, indent=2))
    else:
        print("growr playbook | activity | %s" % report["status"])
        for item in report["transactions"]:
            print(
                "%s [%s]" % (display(item["signature"]), item["detail_status"])
            )
        print(
            "Use --json for transaction evidence, receipts and continuations."
        )
    return 1 if report["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
