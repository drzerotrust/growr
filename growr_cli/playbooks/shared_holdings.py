"""Compare a saved holder cohort without network or child commands."""

import argparse
import json
from pathlib import Path
from typing import Any

from growr_cli.playbooks.holdings import raw_units, token_amount
from growr_cli.playbooks.reporting import display, display_number
from growr_cli.playbooks.runner import (
    finite_number,
    reject_constant,
    valid_address,
)

COMMON_ASSETS = {
    "So11111111111111111111111111111111111111112": "Wrapped SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
}
MAX_REPORT_BYTES = 10 * 1024 * 1024


def load_report(filename) -> dict[str, Any]:
    """Accept only a bounded, supported saved token-holder report."""

    with Path(filename).open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Saved report exceeds 10 MiB")
    report = json.loads(
        data, parse_constant=reject_constant, parse_float=finite_number
    )
    if (
        report.get("playbook_version") != "1.1"
        or report.get("playbook") != "token_holders"
        or report.get("status") not in {"success", "partial"}
        or not valid_address(report.get("target"))
        or not isinstance(report.get("wallets"), list)
    ):
        raise ValueError("Expected a token_holders playbook 1.1 report")
    return report


def holding_evidence(holding, owner) -> dict[str, Any]:
    """Validate amounts and retain the accounts underlying each sum."""

    amount = raw_units(holding["raw_amount"])
    accounts = holding["accounts"]
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("Holding lacks account evidence")
    seen = set()
    total = 0
    for account in accounts:
        address = account["address"]
        if not valid_address(address) or address in seen:
            raise ValueError("Invalid or duplicate holding account")
        seen.add(address)
        total += raw_units(account["raw_amount"])
    if total != amount or not amount:
        raise ValueError("Holding amount does not match its accounts")
    decimals = holding.get("decimals")
    if decimals is not None and (
        type(decimals) is not int or not 0 <= decimals <= 255
    ):
        raise ValueError("Invalid holding decimals")

    # Copy just the validated account evidence used by this aggregate.
    account_evidence = []
    for account in accounts:
        account_evidence.append(
            {
                "address": account["address"],
                "raw_amount": account["raw_amount"],
                "state": account["state"],
            }
        )
    amount_tokens = None
    if decimals is not None:
        amount_tokens = token_amount(str(amount), decimals)
    return {
        "owner": owner,
        "raw_amount": str(amount),
        "decimals": decimals,
        "amount_tokens": amount_tokens,
        "amount_source": holding.get("amount_source"),
        "accounts": account_evidence,
    }


def group_wallet(wallet) -> list[dict[str, Any]]:
    """Keep each observed mint/program group once per selected owner."""

    groups = []
    seen = set()
    for holding in wallet["holdings"] or []:
        mint = holding["mint"]
        program = holding["token_program"]
        key = (mint, program)
        if (
            not valid_address(mint)
            or program not in {"spl_token", "token_2022"}
            or key in seen
        ):
            raise ValueError("Invalid or duplicate mint group")
        seen.add(key)
        groups.append(
            {
                "mint": mint,
                "token_program": program,
                "common_asset": COMMON_ASSETS.get(mint),
                "owners": [holding_evidence(holding, wallet["address"])],
            }
        )
    return groups


def analyze(report) -> dict[str, Any]:
    """Report overlap within the selected cohort."""

    groups = {}
    complete = set()
    selected = set()
    for wallet in report["wallets"]:
        owner = wallet["address"]
        if not valid_address(owner) or owner in selected:
            raise ValueError("Invalid or duplicate selected owner")
        selected.add(owner)
        if wallet["inventory_complete"] is True:
            if not isinstance(wallet["holdings"], list):
                raise ValueError("Complete inventory has no holdings")
            complete.add(owner)
        for group in group_wallet(wallet):
            key = (group["mint"], group["token_program"])
            if key not in groups:
                groups[key] = group
            else:
                groups[key]["owners"].extend(group["owners"])
    # Compare only the selected cohort and keep unknown inventories
    # separate from wallets confirmed not to hold a given token.
    overlaps = []
    for group in groups.values():
        shared = describe_overlap(group, selected, complete, report["target"])
        if shared is not None:
            overlaps.append(shared)
    overlaps.sort(key=overlap_sort_key)
    return {
        "playbook_version": "1.1",
        "playbook": "shared_holdings",
        "target": report["target"],
        "status": "partial" if complete != selected else "success",
        "selected_owner_count": len(selected),
        "complete_inventory_count": len(complete),
        "source_started_at": report.get("started_at"),
        "source_completed_at": report.get("completed_at"),
        "shared_holdings": overlaps,
        "rpc_calls": 0,
        "notes": [
            "Overlap describes this selected sample, not population "
            "rarity or common control.",
            "Common-asset labels cover only wrapped SOL and USDC; "
            "unlabelled assets are not necessarily rare.",
            "Missing inventories remain unknown. Holdings are present "
            "balances, not purchases.",
        ],
    }


def describe_overlap(group, selected, complete, target):
    """Summarize one shared token and its incomplete owner evidence."""

    owners = set()
    decimals = set()
    for holding in group["owners"]:
        owners.add(holding["owner"])
        if holding["decimals"] is not None:
            decimals.add(holding["decimals"])
    if len(owners) < 2:
        return None

    group.update(
        owner_count=len(owners),
        selected_owner_count=len(selected),
        known_absent=sorted(complete - owners),
        unknown_presence=sorted(selected - complete - owners),
        target_token=group["mint"] == target,
        decimals_conflict=len(decimals) > 1,
    )
    return group


def overlap_sort_key(group) -> tuple[bool, bool, int, str]:
    """Place other assets before the target and known common assets."""

    return (
        group["target_token"],
        group["common_asset"] is not None,
        group["owner_count"],
        group["mint"],
    )


def main(argv=None) -> int:
    """Read a saved report and print exact shared quantities."""

    parser = argparse.ArgumentParser(
        prog="growr playbook shared-holdings",
        description="Find shared holdings in a saved token_holders JSON "
        "report; zero network calls.",
        epilog="Example: growr playbook shared-holdings holders.json --json",
    )
    parser.add_argument("report")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    try:
        report = load_report(options.report)
        result = analyze(report)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        result = {
            "playbook_version": "1.1",
            "playbook": "shared_holdings",
            "status": "error",
            "error": "invalid_saved_report",
        }
    if options.json:
        print(json.dumps(result, allow_nan=False, indent=2))
    else:
        print("growr playbook | shared_holdings | %s" % result["status"])
        for group in result.get("shared_holdings", []):
            print(
                "%s: %s/%s selected owners"
                % (
                    display(group["mint"]),
                    group["owner_count"],
                    group["selected_owner_count"],
                )
            )
            for owner in group["owners"]:
                amount = owner["amount_tokens"]
                if amount is None:
                    quantity = "%s raw units" % display_number(
                        owner["raw_amount"]
                    )
                else:
                    quantity = "%s tokens" % display_number(amount)
                print("  %s: %s" % (display(owner["owner"]), quantity))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
