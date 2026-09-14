"""Decode wallet inventory entries from already fetched RPC accounts."""

from typing import Any

from solders.pubkey import Pubkey

from growr_cli.solana.decoding import parse_token_account


def token_account_entries(
    accounts, wallet, program
) -> tuple[list[dict[str, Any]], int]:
    """Keep validated holdings and count entries that cannot be used."""

    entries = []
    rejected = 0
    seen = set()
    for item in accounts:
        try:
            entry = _token_account_entry(item, wallet, program)
            if entry["address"] in seen:
                raise ValueError("Duplicate token-account address")
        except (AttributeError, TypeError, ValueError):
            # A bad row must not hide other holdings or become a claim
            # about this wallet. Count the gap without echoing payloads.
            rejected += 1
            continue
        seen.add(entry["address"])
        entries.append(entry)
    return entries, rejected


def _token_account_entry(item, wallet, program) -> dict[str, Any]:
    """Check the owning program and decoded wallet authority."""

    address = str(Pubkey.from_string(str(item.pubkey)))
    account = item.account
    owner_program = str(account.owner)
    if owner_program != str(program) or account.executable:
        raise ValueError("Account does not belong to the queried program")
    parsed = parse_token_account(account.data, owner_program)
    if parsed["owner"] != str(wallet):
        raise ValueError("Token account belongs to another wallet")
    return {
        "address": address,
        "mint": parsed["mint"],
        "token_program": parsed["token_program"],
        "raw_amount": parsed["raw_amount"],
        "state": parsed["state"],
    }
