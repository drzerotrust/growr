"""Select sampled owners and aggregate exact wallet token quantities."""

from dataclasses import dataclass, field
from typing import Any

from growr_cli.playbooks.runner import GrowrRunner, valid_address


def raw_units(value) -> int:
    """Require nonnegative integer strings, preserving native units."""

    if not isinstance(value, str) or not (
        value.isascii() and value.isdecimal()
    ):
        raise ValueError("Invalid raw balance")
    return int(value)


def token_amount(raw, decimals) -> str:
    """Insert a decimal point without floating-point rounding."""

    digits = str(raw_units(raw))
    if decimals == 0:
        return digits
    digits = digits.rjust(decimals + 1, "0")
    amount = "%s.%s" % (digits[:-decimals], digits[-decimals:])
    return amount.rstrip("0").rstrip(".")


def mint_details(record) -> dict[str, Any]:
    """Read mint units and optional names from the RPC scan facts."""

    facts = record["facts"]
    mint = facts["mint"]
    decimals = mint["decimals"]
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Invalid mint decimals")
    program = mint["token_program"]
    if program not in {"spl_token", "token_2022"}:
        raise ValueError("Invalid mint program")
    metadata = facts.get("metadata") or {}
    return {
        "status": "resolved",
        "source": "rpc",
        "decimals": decimals,
        "token_program": program,
        "name": metadata.get("name"),
        "symbol": metadata.get("symbol"),
    }


@dataclass
class MintResolver:
    """Cache successful and failed mint lookups across all wallets."""

    runner: GrowrRunner
    limit: int
    lookups: int = field(default=0, init=False)
    cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def seed(self, mint, record) -> None:
        """Reuse the initial target-token scan for its decimals."""

        self.cache[mint] = mint_details(record)

    def resolve(self, mint) -> dict[str, Any]:
        """Try each mint once and explain any missing units."""

        if mint in self.cache:
            return self.cache[mint]
        result = {"status": "not_requested"}
        if self.limit and self.lookups >= self.limit:
            result["status"] = "budget_exhausted"
        elif self.limit:
            self.lookups += 1
            record = self.runner.scan("token", mint)
            result["status"] = "failed"
            if record is not None:
                try:
                    result = mint_details(record)
                except (ValueError, KeyError, TypeError, AttributeError):
                    result["status"] = "invalid_mint_facts"
        self.cache[mint] = result
        return result


def sampled_owners(record, limit) -> dict[str, Any]:
    """Rank owners by summed balances within the account sample."""

    details = mint_details(record)
    rows = record["facts"]["holders"]["top_accounts"]
    if not isinstance(rows, list) or len(rows) > 20:
        raise ValueError("Invalid largest-account sample")
    owners = {}
    unresolved = []
    seen_accounts = set()
    for rank, row in enumerate(rows, 1):
        account = row["token_account"]
        amount = raw_units(row["raw_amount"])
        if not valid_address(account) or account in seen_accounts:
            raise ValueError("Invalid or repeated sample account")
        seen_accounts.add(account)
        entry = {
            "rank": rank,
            "token_account": account,
            "raw_amount": str(amount),
            "amount_tokens": token_amount(str(amount), details["decimals"]),
        }
        owner = row.get("owner")
        if not valid_address(owner):
            unresolved.append(entry)
            continue
        if amount:
            if owner not in owners:
                owners[owner] = [entry]
            else:
                owners[owner].append(entry)
    selected = []
    for owner, accounts in owners.items():
        total_raw_amount = 0
        for account in accounts:
            total_raw_amount += int(account["raw_amount"])

        selected.append(
            {
                "address": owner,
                "sample_raw_amount": str(total_raw_amount),
                "sample_accounts": accounts,
            }
        )
    # Ranking describes only this sample. Wallet scans later observe
    # all returned accounts, at separate timestamps, for each owner.
    selected.sort(key=owner_sample_amount, reverse=True)
    for owner in selected:
        owner["sample_amount_tokens"] = token_amount(
            owner["sample_raw_amount"], details["decimals"]
        )
    return {
        "accounts_returned": len(rows),
        "resolved_nonzero_owners": len(selected),
        "unresolved_accounts": unresolved,
        "owners_not_selected": max(0, len(selected) - limit),
        "owners": selected[:limit],
    }


def owner_sample_amount(owner) -> int:
    """Sort sampled owner balances as numbers, not integer strings."""

    return int(owner["sample_raw_amount"])


def holding_group(mint, program, target) -> dict[str, Any]:
    """Describe an aggregate without discarding its account evidence."""

    return {
        "mint": mint,
        "token_program": program,
        "is_target": mint == target,
        "raw_amount": "0",
        "accounts": [],
    }


def group_accounts(entries, target) -> tuple[list[dict[str, Any]], int]:
    """Sum same-mint accounts and retain individual evidence."""

    if not isinstance(entries, list):
        raise ValueError("Invalid wallet entries")
    groups = {}
    seen = set()
    zero_count = 0
    for entry in entries:
        account = entry["address"]
        mint = entry["mint"]
        amount = raw_units(entry["raw_amount"])
        program = entry["token_program"]
        state = entry["state"]
        if (
            not valid_address(account)
            or not valid_address(mint)
            or account in seen
            or program not in {"spl_token", "token_2022"}
            or state not in {"uninitialized", "initialized", "frozen"}
        ):
            raise ValueError("Invalid wallet account")
        seen.add(account)
        if not amount:
            zero_count += 1
            continue
        key = (mint, program)
        if key not in groups:
            groups[key] = holding_group(mint, program, target)
        group = groups[key]
        group["raw_amount"] = str(int(group["raw_amount"]) + amount)
        group["accounts"].append(
            {"address": account, "raw_amount": str(amount), "state": state}
        )
    return list(groups.values()), zero_count


def resolve_amounts(holdings, resolver, metadata=None) -> None:
    """Convert units only when the mint program also matches."""

    metadata_by_mint = metadata or {}
    for holding in holdings:
        information = metadata_by_mint.get(
            holding["mint"], {"source": "jupiter", "status": "skipped"}
        )
        details = amount_details(holding, resolver, information)
        status = details["status"]
        if status == "resolved" and (
            details["token_program"] != holding["token_program"]
        ):
            status = "program_mismatch"
        # Unknown units stay unknown; never guess a decimal scale.
        decimals = None
        amount_tokens = None
        amount_source = None
        if status == "resolved":
            decimals = details["decimals"]
            amount_tokens = token_amount(holding["raw_amount"], decimals)
            amount_source = details.get("source")
        holding.update(
            amount_status=status,
            amount_source=amount_source,
            decimals=decimals,
            amount_tokens=amount_tokens,
            name=information.get("name") or details.get("name"),
            symbol=information.get("symbol") or details.get("symbol"),
            metadata=information,
        )


def amount_details(holding, resolver, metadata) -> dict[str, Any]:
    """Prefer RPC units, then Jupiter, then bounded RPC fallback."""

    mint = holding["mint"]
    known = resolver.cache.get(mint, {})
    jupiter = metadata.get("units", {"status": metadata["status"]})
    if jupiter["status"] == "resolved" and (
        jupiter["token_program"] != holding["token_program"]
    ):
        jupiter = {"status": "program_mismatch"}
    holding["metadata_conflicts"] = []
    if known.get("status") == "resolved":
        if jupiter["status"] == "program_mismatch":
            holding["metadata_conflicts"].append("token_program")
        elif jupiter["status"] == "resolved" and (
            jupiter["decimals"] != known["decimals"]
        ):
            holding["metadata_conflicts"].append("decimals")
        return known
    if jupiter["status"] == "resolved":
        return jupiter
    fallback = resolver.resolve(mint)
    if fallback["status"] == "not_requested" and metadata["status"] != (
        "skipped"
    ):
        return jupiter
    return fallback


def wallet_inventory(address, record, target=None) -> dict[str, Any]:
    """Distinguish failed inventories from empty wallets."""

    result = {
        "address": address,
        "status": "failed",
        "inventory_complete": False,
        "sol_balance": None,
        "sol_lamports": None,
        "holdings": None,
        "zero_accounts_omitted": None,
        "unparsed_account_count": None,
    }
    if record is None:
        return result
    try:
        facts = record["facts"]
        inventory = facts["token_accounts"]
        lamports = facts.get("sol_lamports")
        lamports = str(raw_units(lamports)) if lamports is not None else None
        holdings, zero_count = group_accounts(inventory["entries"], target)
        known_inventory, complete = inventory_coverage(inventory)
    except (ValueError, KeyError, TypeError):
        result["error"] = "invalid_wallet_facts"
        return result
    result.update(
        status="success" if complete else "partial",
        inventory_complete=complete,
        sol_balance=record["facts"].get("sol_balance"),
        sol_lamports=lamports,
        holdings=holdings if known_inventory else None,
        zero_accounts_omitted=zero_count if known_inventory else None,
        unparsed_account_count=inventory["unparsed_account_count"],
    )
    return result


def inventory_coverage(inventory) -> tuple[bool, bool]:
    """Distinguish a usable response from a complete inventory."""

    unparsed = inventory["unparsed_account_count"]
    if type(unparsed) is not int or unparsed < 0:
        raise ValueError("Invalid inventory count")

    known_inventory = False
    for key in ("spl_token_account_count", "token_2022_account_count"):
        if inventory[key] is not None:
            known_inventory = True
            break

    # Complete coverage requires both programs and no unparsed entries.
    complete = unparsed == 0
    if complete:
        for key in ("spl_token_account_count", "token_2022_account_count"):
            count = inventory[key]
            if type(count) is not int or count < 0:
                complete = False
                break
    return known_inventory, complete
