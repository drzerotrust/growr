"""Read and interpret Solana holders data."""

from itertools import zip_longest
from typing import Any

from solders.pubkey import Pubkey


def read_holders(rpc, mint, supply_text, decimals) -> dict[str, Any]:
    """Inspect largest accounts and resolve their owners."""

    supply = int(supply_text)
    largest_accounts = rpc.get_largest_token_accounts(mint)
    addresses = [entry.address for entry in largest_accounts]
    raw_accounts = rpc.get_multiple_accounts(addresses)
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
        owner = None
        if raw_account is not None:
            account_data = rpc.extract_bytes(raw_account.data)
            if len(account_data) >= 64:
                owner = str(Pubkey.from_bytes(account_data[32:64]))
        percent = 0.0
        if supply > 0:
            percent = (amount / supply) * 100
        holders.append(
            {
                "token_account": str(entry.address),
                "owner": owner,
                "raw_amount": str(amount),
                "ui_amount": amount / (10**decimals),
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
