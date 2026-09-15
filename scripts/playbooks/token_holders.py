"""Follow a token's sampled owners into their other current holdings.

Run from the project root:
    python3 scripts/playbooks/token_holders.py <MINT> --json
"""

import sys
from pathlib import Path
from typing import Any

# Support both direct script execution and python -m invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.playbooks.holdings import (
    MintResolver,
    sampled_owners,
    wallet_inventory,
)
from scripts.playbooks.metadata import enrich_wallets
from scripts.playbooks.reporting import (
    build_parser,
    finish_report,
    new_report,
    print_report,
    subprocess_limit,
)
from scripts.playbooks.runner import GrowrRunner


def investigate(options, runner) -> dict[str, Any]:
    """Scan owners and enrich their holdings with shared metadata."""

    report = new_report("token_holders", options)
    resolver = MintResolver(runner, options.mint_limit)
    record = runner.scan("token", options.address)
    report["notes"].append(
        "Owner ranking sums only the returned largest-account sample, "
        "not all holders. Selecting fewer owners limits the scope."
    )
    if record is None:
        report.update(status="error", error="target_scan_failed")
        return finish_report(report, runner, resolver)
    try:
        resolver.seed(options.address, record)
        sample = sampled_owners(record, options.wallet_limit)
    except (ValueError, KeyError, TypeError, AttributeError):
        report.update(status="error", error="invalid_token_facts")
        return finish_report(report, runner, resolver)
    report["sample"] = sample
    if sample["unresolved_accounts"]:
        report["status"] = "partial"
    elif not sample["owners"]:
        report["status"] = "no_data"

    # Finish wallet discovery before spending the separate mint budget.
    # Owners and mints are deduplicated; metadata scans never recurse.
    for owner in sample["owners"]:
        record = runner.scan("wallet", owner["address"])
        wallet = wallet_inventory(owner["address"], record, options.address)
        wallet.update(owner)
        report["wallets"].append(wallet)
    enrich_wallets(report, resolver, options)
    return finish_report(report, runner, resolver)


def main(argv=None) -> int:
    """Run the bounded token-to-wallet recipe and emit its report."""

    options = build_parser("token_holders").parse_args(argv)
    runner = GrowrRunner(options.timeout, subprocess_limit(options))
    return print_report(investigate(options, runner), options.json)


if __name__ == "__main__":
    raise SystemExit(main())
