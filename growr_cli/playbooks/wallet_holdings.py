"""Aggregate one wallet's holdings through Growr subprocess commands.

Run from the project root:
    growr playbook wallet-holdings <WALLET> --json
"""

from typing import Any

# Support both direct script execution and python -m invocation.
from growr_cli.playbooks.holdings import (
    MintResolver,
    wallet_inventory,
)
from growr_cli.playbooks.metadata import enrich_wallets
from growr_cli.playbooks.reporting import (
    build_parser,
    finish_report,
    new_report,
    print_report,
    subprocess_limit,
)
from growr_cli.playbooks.runner import GrowrRunner


def investigate(options, runner) -> dict[str, Any]:
    """Read accounts and enrich holdings with shared metadata."""

    report = new_report("wallet_holdings", options)
    resolver = MintResolver(runner, options.mint_limit)
    record = runner.scan("wallet", options.address)
    wallet = wallet_inventory(options.address, record)
    report["wallets"].append(wallet)
    if wallet["status"] == "failed":
        report.update(status="error", error="wallet_inventory_failed")
    else:
        enrich_wallets(report, resolver, options)
    return finish_report(report, runner, resolver)


def main(argv=None) -> int:
    """Run the standalone wallet recipe and emit its report."""

    options = build_parser("wallet_holdings").parse_args(argv)
    runner = GrowrRunner(options.timeout, subprocess_limit(options))
    return print_report(investigate(options, runner), options.json)


if __name__ == "__main__":
    raise SystemExit(main())
