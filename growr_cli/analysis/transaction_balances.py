"""Exact balances, separate from transfer interpretation."""

from typing import Any


def account_keys(message, meta) -> tuple[list[str], list[str]]:
    """Resolve legacy/raw keys or already expanded jsonParsed keys."""

    entries = message["accountKeys"]
    if all(isinstance(item, dict) for item in entries):
        return (
            [item["pubkey"] for item in entries],
            [item["pubkey"] for item in entries if item["signer"]],
        )
    # Raw messages list static keys first, then loaded writable/readonly
    # keys. Parsed messages already include those lookup-table entries.
    loaded = meta.get("loadedAddresses") or {}
    keys = entries + loaded.get("writable", []) + loaded.get("readonly", [])
    signers = entries[: message["header"]["numRequiredSignatures"]]
    return keys, signers


def native_balances(keys, meta) -> list[dict[str, Any]]:
    """Preserve lamports and deltas; changes include fees and rent."""

    before = meta.get("preBalances")
    after = meta.get("postBalances")
    if before is None or after is None:
        return []
    if len(before) != len(keys) or len(after) != len(keys):
        raise ValueError("Transaction balance keys do not match")
    return [
        {
            "address": key,
            "before_lamports": str(start),
            "after_lamports": str(end),
            "delta_lamports": str(end - start),
        }
        for key, start, end in zip(keys, before, after, strict=True)
    ]


def token_balances(keys, meta) -> list[dict[str, Any]]:
    """Missing sides stay unknown, including created/closed accounts."""

    observations = {}
    for side, field in (
        ("before", "preTokenBalances"),
        ("after", "postTokenBalances"),
    ):
        for item in meta.get(field) or []:
            index = item["accountIndex"]
            if type(index) is not int or not 0 <= index < len(keys):
                raise ValueError("Invalid token balance account index")
            units = item["uiTokenAmount"]
            key = (index, item["mint"])
            if key not in observations:
                observations[key] = {
                    "token_account": keys[index],
                    "mint": item["mint"],
                    "before": None,
                    "after": None,
                    "delta_raw": None,
                }
            row = observations[key]
            if row[side] is not None:
                raise ValueError("Duplicate token balance observation")
            row[side] = {
                "raw_amount": units["amount"],
                "decimals": units["decimals"],
                "owner": item.get("owner"),
                "program_id": item.get("programId"),
            }
    for row in observations.values():
        before, after = row["before"], row["after"]
        if before and after and before["decimals"] == after["decimals"]:
            row["delta_raw"] = str(
                int(after["raw_amount"]) - int(before["raw_amount"])
            )
    return list(observations.values())
