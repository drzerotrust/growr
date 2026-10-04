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
    facts = mapping(record.get("facts"))
    if facts.get("source") != sources[kind]:
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

    # Use successful reads from this source only. Any malformed time
    # makes the source timing unreliable, so use the retrieval time.
    fetched_times = []
    for coverage in record["coverage"]:
        if not isinstance(coverage, dict):
            continue
        if coverage.get("source") != source:
            continue
        if coverage.get("status") != "success":
            continue
        fetched_at = coverage.get("fetched_at")
        if not fetched_at:
            continue
        fetched_time = timestamp(fetched_at)
        if fetched_time is None:
            return fallback
        fetched_times.append(fetched_time)

    if not fetched_times:
        return fallback
    return max(fetched_times).isoformat()


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
    rows = []
    for field, key in pairs.items():
        row = measurement(
            record,
            field,
            values.get(key),
            "jupiter",
            "token",
            "metrics.jupiter.values.%s" % key,
            fallback,
            index,
        )
        rows.append(row)

    # Volume combines buys and sells from the same 24-hour window.
    volume = jupiter_volume_24h(values)
    volume_row = measurement(
        record,
        "volume_24h_usd",
        volume,
        "jupiter",
        "token",
        "metrics.jupiter.values.activity.24h.buyVolume+sellVolume",
        fallback,
        index,
    )
    rows.append(volume_row)

    age_hours = first_pool_age_hours(values, as_of)
    age_row = measurement(
        record,
        "first_pool_age_hours",
        age_hours,
        "jupiter",
        "token",
        "metrics.jupiter.values.first_pool.createdAt",
        fallback,
        index,
    )
    rows.append(age_row)
    return rows


def jupiter_volume_24h(values) -> str | None:
    """Sum known nonnegative volumes from the 24-hour window."""

    activity = mapping(values.get("activity"))
    daily_stats = mapping(activity.get("24h"))
    buy_volume = decimal_value(daily_stats.get("buyVolume"))
    sell_volume = decimal_value(daily_stats.get("sellVolume"))
    if buy_volume is None or sell_volume is None:
        return None
    if buy_volume < 0 or sell_volume < 0:
        return None
    return str(buy_volume + sell_volume)


def first_pool_age_hours(values, as_of) -> float | None:
    """Measure pool age; do not confuse it with token creation time."""

    first_pool = mapping(values.get("first_pool"))
    created_at = timestamp(first_pool.get("createdAt"))
    if created_at is None:
        return None
    elapsed = as_of - created_at
    return elapsed.total_seconds() / 3600


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
        group_metrics = mapping(metrics.get(group))
        item = mapping(group_metrics.get(key))
        source = item.get("source")
        scope = item.get("scope")
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
    sources = []
    for source in ("jupiter", "stonks"):
        if coverage.get(source) == "success":
            sources.append(source)
    if not sources:
        return []
    # Merged social scores describe presence, not authenticity.
    # Use the oldest participating source time for its freshness bound.
    observed = social_observed_at(record, sources, fallback)
    platforms = social.get("platforms")
    has_social = bool(platforms) if isinstance(platforms, list) else None
    fields = {
        "has_website": social.get("has_website"),
        "has_social": has_social,
        "social_score": social.get("score"),
    }
    incomplete = False
    for state in coverage.values():
        if state not in {"success", "skipped", "no_data"}:
            incomplete = True

    rows = []
    for field, value in fields.items():
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


def social_observed_at(record, sources, fallback) -> str | None:
    """Date merged social evidence by its oldest contributing source."""

    source_times = []
    for source in sources:
        observed = observed_at(record, source, fallback)
        source_time = timestamp(observed)
        if source_time is None:
            return None
        source_times.append(source_time)
    return min(source_times).isoformat()


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
    rows = []
    for name, value in fields.items():
        row = measurement(
            record, name, value, "rpc", "token", "facts.mint", fallback, index
        )
        rows.append(row)
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

    candidates = {}
    for mint in mints:
        candidates[mint] = {
            "mint": mint,
            "observations": [],
            "evidence_indices": [],
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
