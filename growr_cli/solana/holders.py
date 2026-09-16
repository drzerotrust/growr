"""Read and interpret Solana holders data."""

from itertools import zip_longest
from typing import Any

from growr_cli.solana.decoding import parse_token_account
from growr_cli.solana.rpc import RpcError


def read_holders(
    rpc, mint, supply_text, decimals, program=None
) -> dict[str, Any]:
    """Inspect largest accounts and resolve their owners."""

    supply = int(supply_text)
    largest_accounts = rpc.get_largest_token_accounts(mint)
    addresses = [entry.address for entry in largest_accounts]
    try:
        raw_accounts = rpc.get_multiple_accounts(addresses)
    except RpcError:
        raw_accounts = []
    holders = []
    top_twenty_amount = 0

    # Keep amounts when owner-account reads are missing. These are
    # account totals, not a deduplicated graph of wallet owners.
    for entry, raw_account in zip_longest(largest_accounts, raw_accounts):
        if entry is None:
            break
        # The SDK wraps the raw integer string in UiTokenAmount.
        amount = int(entry.amount.amount)
        top_twenty_amount += amount
        owner = validated_owner(rpc, raw_account, mint, program)
        percent = 0.0
        if supply > 0:
            percent = (amount / supply) * 100
        holders.append(
            {
                "token_account": str(entry.address),
                "owner": owner,
                "raw_amount": str(amount),
                "ui_amount": amount / (10**decimals),
                "amount_tokens": exact_amount(amount, decimals),
                "percent_of_supply": round(percent, 4),
            }
        )

    top_twenty_percent = 0.0
    if supply > 0:
        top_twenty_percent = round((top_twenty_amount / supply) * 100, 4)
    return {
        "top_accounts": holders,
        "top_twenty_percent": top_twenty_percent,
        "note": "Largest token accounts can include pools, lockers, and "
        "burn accounts.",
    }


def exact_amount(amount, decimals) -> str:
    """Insert a decimal point without rounding native amounts."""

    digits = str(amount).zfill(decimals + 1)
    return (
        (digits[:-decimals] + "." + digits[-decimals:]).rstrip("0").rstrip(".")
        if decimals
        else digits
    )


def validated_owner(rpc, account, mint, program=None) -> str | None:
    """Resolve only nonexecutable token accounts for the exact mint."""

    try:
        if account is None or account.executable:
            return None
        if program is not None and str(account.owner) != str(program):
            return None
        parsed = parse_token_account(
            rpc.extract_bytes(account.data), str(account.owner)
        )
        if parsed["mint"] != str(mint) or parsed["state"] == "uninitialized":
            return None
        return parsed["owner"]
    except (AttributeError, TypeError, ValueError):
        return None
