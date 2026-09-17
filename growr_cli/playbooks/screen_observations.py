"""Read screening measurements from Growr's public JSON records."""

from typing import Any

from growr_cli.playbooks.runner import valid_address
from growr_cli.playbooks.screening import (
    BOOLEAN_FIELDS,
    NUMERIC_FIELDS,
    decimal_value,
    timestamp,
)


def mapping(value) -> dict[str, Any]:
    """Treat absent optional objects as missing measurements."""

    return value if isinstance(value, dict) else {}


def validate_record(record) -> None:
    """Require exact Solana identities and recognized sources."""

    if not isinstance(record, dict):
        raise ValueError("Expected a Growr record")
    identity = mapping(record.get("identity"))
    mint = identity.get("mint")
    kind = record.get("kind")
    sources = {"token": "rpc", "pool": "stonks", "token_discovery": "jupiter"}
    if not isinstance(kind, str) or kind not in sources:
        raise ValueError("Expected token or discovery evidence")
    if identity.get("chain") != "solana" or not valid_address(mint):
        raise ValueError("Expected a valid Solana mint")
    if kind == "token" and identity.get("address") != mint:
        raise ValueError("Mismatched RPC mint identity")
    if mapping(record.get("facts")).get("source") != sources[kind]:
        raise ValueError("Mismatched record source")
    if not isinstance(record.get("metrics"), dict):
        raise ValueError("Expected sourced metrics")
    if not isinstance(record.get("coverage"), list):
        raise ValueError("Expected record coverage")
    pool = identity.get("pool")
    if pool is not None and not valid_address(pool):
        raise ValueError("Invalid pool address")


def observed_at(record, source, fallback) -> str | None:
    """Prefer provider time, with retrieval time as a fallback."""

    jupiter = mapping(record["metrics"].get("jupiter"))
    values = mapping(jupiter.get("values"))
    if source == "jupiter" and values.get("updated_at") is not None:
        return values["updated_at"]
    times = [
        item["fetched_at"]
        for item in record["coverage"]
        if isinstance(item, dict)
        and item.get("source") == source
        and item.get("status") == "success"
        and item.get("fetched_at")
    ]
    moments = [timestamp(value) for value in times]
    valid = [moment for moment in moments if moment is not None]
    return (
        max(valid).isoformat()
        if len(valid) == len(times) and valid
        else fallback
    )


def measurement(record, field, value, source, scope, path, fallback, index):
    """Attach source, units, time and an original-record pointer."""

    if field in NUMERIC_FIELDS:
        number = decimal_value(value)
        value = str(number) if number is not None and number >= 0 else None
    if field in BOOLEAN_FIELDS and type(value) is not bool:
        value = None
    if field == "category" and not isinstance(value, str):
        value = None
    return {
        "field": field,
        "value": value,
        "source": source,
        "scope": scope,
        "observed_at": observed_at(record, source, fallback),
        "evidence_index": index,
        "path": path,
        "pool": record["identity"].get("pool") if scope == "pool" else None,
        "priority": 1 if source == "stonks" else 0,
    }


def jupiter_observations(
    record, fallback, index, as_of
) -> list[dict[str, Any]]:
    """Read Jupiter's token-level summary and same-interval volume."""

    block = mapping(record["metrics"].get("jupiter"))
    if block.get("source") != "jupiter" or block.get("scope") != "token":
        return []
    values = mapping(block.get("values"))
    pairs = {
        "market_cap_usd": "market_cap",
        "liquidity_usd": "liquidity",
        "holder_count": "holder_count",
        "organic_score": "organic_score",
        "verified": "verified",
    }
    rows = [
        measurement(
            record,
            field,
            values.get(key),
            "jupiter",
            "token",
            "metrics.jupiter.values.%s" % key,
            fallback,
            index,
        )
        for field, key in pairs.items()
    ]
    stats = mapping(mapping(values.get("activity")).get("24h"))
    buy, sell = (
        decimal_value(stats.get("buyVolume")),
        decimal_value(stats.get("sellVolume")),
    )
    total = str(buy + sell) if buy is not None and sell is not None else None
    if buy is not None and sell is not None and (buy < 0 or sell < 0):
        total = None
    rows.append(
        measurement(
            record,
            "volume_24h_usd",
            total,
            "jupiter",
            "token",
            "metrics.jupiter.values.activity.24h.buyVolume+sellVolume",
            fallback,
            index,
        )
    )
    created = timestamp(mapping(values.get("first_pool")).get("createdAt"))
    age = (as_of - created).total_seconds() / 3600 if created else None
    rows.append(
        measurement(
            record,
            "first_pool_age_hours",
            age,
            "jupiter",
            "token",
            "metrics.jupiter.values.first_pool.createdAt",
            fallback,
            index,
        )
    )
    return rows


def pooled_observations(record, fallback, index) -> list[dict[str, Any]]:
    """Retain combined metrics' original token or pool scope."""

    metrics = record["metrics"]
    paths = (
        ("market_cap_usd", "market", "market_cap_usd"),
        ("liquidity_usd", "market", "token_liquidity_usd"),
        ("volume_24h_usd", "market", "stonks_volume_24h_usd"),
        ("holder_count", "risk", "holderCount"),
        ("organic_score", "risk", "organicScore"),
        ("verified", "risk", "isVerified"),
    )
    rows = []
    for field, group, key in paths:
        item = mapping(mapping(metrics.get(group)).get(key))
        source, scope = item.get("source"), item.get("scope")
        valid_scope = (source, scope) in {
            ("jupiter", "token"),
            ("stonks", "pool"),
        }
        token_only = {
            "liquidity_usd",
            "holder_count",
            "organic_score",
            "verified",
        }
        if not valid_scope or (field in token_only and source != "jupiter"):
            continue
        rows.append(
            measurement(
                record,
                field,
                item.get("value"),
                source,
                scope,
                "metrics.%s.%s.value" % (group, key),
                fallback,
                index,
            )
        )
    rows.append(
        measurement(
            record,
            "category",
            record["facts"].get("quote_category"),
            "stonks",
            "pool",
            "facts.quote_category",
            fallback,
            index,
        )
    )
    return rows


def social_observations(record, fallback, index) -> list[dict[str, Any]]:
    """Read social presence with explicit provider coverage."""

    social = mapping(record.get("social"))
    coverage = mapping(social.get("coverage"))
    sources = sorted(
        key for key in ("jupiter", "stonks") if coverage.get(key) == "success"
    )
    if not sources:
        return []
    # Merged social scores describe presence, not authenticity.
    # Use the oldest participating source time for its freshness bound.
    times = [observed_at(record, source, fallback) for source in sources]
    moments = [timestamp(value) for value in times]
    valid = [moment for moment in moments if moment is not None]
    observed = min(valid).isoformat() if len(valid) == len(times) else None
    platforms = social.get("platforms")
    has_social = bool(platforms) if isinstance(platforms, list) else None
    fields = {
        "has_website": social.get("has_website"),
        "has_social": has_social,
        "social_score": social.get("score"),
    }
    rows = []
    for field, value in fields.items():
        incomplete = any(
            state not in {"success", "skipped", "no_data"}
            for state in coverage.values()
        )
        if incomplete and (value is False or field == "social_score"):
            value = None
        row = measurement(
            record,
            field,
            value,
            "growr",
            "token",
            "social",
            fallback,
            index,
        )
        row.update(observed_at=observed, sources=sources)
        rows.append(row)
    return rows


def rpc_observations(record, fallback, index) -> list[dict[str, Any]]:
    """Distinguish missing authorities from explicit revocations."""

    mint = mapping(record["facts"].get("mint"))
    fields = {"initialized_mint": mint.get("initialized")}
    for name in ("mint_authority", "freeze_authority"):
        value = mint.get(name)
        revoked = None
        if name in mint and (value is None or valid_address(value)):
            revoked = value is None
        fields["%s_revoked" % name] = revoked
    rows = [
        measurement(
            record, name, value, "rpc", "token", "facts.mint", fallback, index
        )
        for name, value in fields.items()
    ]
    holders = mapping(record["facts"].get("holders"))
    supply = decimal_value(mint.get("supply"))
    concentration = (
        holders.get("top_twenty_percent")
        if supply is not None and supply > 0
        else None
    )
    rows.append(
        measurement(
            record,
            "top_20_accounts_pct",
            concentration,
            "rpc",
            "token",
            "facts.holders.top_twenty_percent",
            fallback,
            index,
        )
    )
    return rows


def candidates_from_evidence(evidence, mints, as_of) -> list[dict[str, Any]]:
    """Deduplicate mints and retain source and pool observations."""

    candidates = {
        mint: {"mint": mint, "observations": [], "evidence_indices": []}
        for mint in mints
    }
    for index, entry in enumerate(evidence):
        record = entry["record"]
        validate_record(record)
        mint = record["identity"]["mint"]
        if mint not in candidates:
            continue
        fallback = entry["retrieved_at"]
        if record["kind"] == "token":
            rows = rpc_observations(record, fallback, index)
        else:
            rows = jupiter_observations(record, fallback, index, as_of)
            if record["kind"] == "pool":
                rows.extend(pooled_observations(record, fallback, index))
            rows.extend(social_observations(record, fallback, index))
        candidates[mint]["observations"].extend(rows)
        candidates[mint]["evidence_indices"].append(index)
    return list(candidates.values())
