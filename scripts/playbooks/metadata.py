"""Enrich wallet holdings through bounded Growr Jupiter searches."""

from typing import Any

from spl.token.constants import TOKEN_2022_PROGRAM_ID, TOKEN_PROGRAM_ID

from scripts.playbooks.holdings import resolve_amounts

TOKEN_PROGRAMS = {
    str(TOKEN_PROGRAM_ID): "spl_token",
    str(TOKEN_2022_PROGRAM_ID): "token_2022",
}


def metadata_details(record) -> dict[str, Any]:
    """Keep Jupiter metadata separate from RPC evidence."""

    values = record["metrics"]["jupiter"]["values"]
    result = {
        "source": "jupiter",
        "status": "success",
        "social": record["social"],
        "coverage": record["coverage"],
        "units": jupiter_units(values),
    }
    for key in ("name", "symbol", "icon", "token_program", "updated_at"):
        value = values.get(key)
        result[key] = value if isinstance(value, str) else None
    verified = values.get("verified")
    result["verified"] = verified if type(verified) is bool else None
    price = values.get("price_usd")
    result["price_usd"] = (
        price if type(price) in {int, float} and price >= 0 else None
    )
    return result


def jupiter_units(values) -> dict[str, Any]:
    """Validate decimals and the token program before scaling."""

    decimals = values.get("decimals")
    if decimals is None:
        return {"status": "missing_decimals"}
    if type(decimals) is not int or not 0 <= decimals <= 255:
        return {"status": "invalid_decimals"}
    program = values.get("token_program")
    if not isinstance(program, str) or program not in TOKEN_PROGRAMS:
        return {"status": "unknown_token_program"}
    return {
        "source": "jupiter",
        "status": "resolved",
        "decimals": decimals,
        "token_program": TOKEN_PROGRAMS[program],
    }


def fetch_metadata(mints, runner, batch_limit) -> dict[str, Any]:
    """Cache one outcome per mint across sequential batches of 100."""

    mints = list(dict.fromkeys(mints))
    cache = {}
    for offset in range(0, len(mints), 100):
        batch = mints[offset : offset + 100]
        requested = offset < batch_limit * 100
        status = "skipped" if batch_limit == 0 else "budget_exhausted"
        for mint in batch:
            cache[mint] = {
                "source": "jupiter",
                "status": status,
                "scan_index": len(runner.scans) if requested else None,
            }
        if not requested:
            continue
        records = runner.search(batch)
        status = "failed" if records is None else "no_data"
        # Keep missing IDs explicit. A successful response may omit
        # tokens Jupiter has not indexed, even within a known wallet.
        for mint in batch:
            cache[mint]["status"] = status
        for record in records or []:
            cache[record["identity"]["mint"]].update(metadata_details(record))
    return cache


def enrich_wallets(report, resolver, options) -> None:
    """Share wallet metadata before optional RPC fallback."""

    holdings = [
        holding
        for wallet in report["wallets"]
        for holding in wallet["holdings"] or []
    ]
    limit = 0 if options.no_jupiter else options.jupiter_batch_limit
    metadata = fetch_metadata(
        [holding["mint"] for holding in holdings], resolver.runner, limit
    )
    report["metadata_lookups"] = metadata
    resolve_amounts(holdings, resolver, metadata)
