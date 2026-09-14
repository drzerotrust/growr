"""Normalize existing reports into agent-facing evidence records."""

from datetime import datetime, timezone
from typing import Any

from growr_cli.analysis.metrics import mapping
from growr_cli.models import ScanReport


def coverage(
    source, operation, status, detail="", fetched_at=None
) -> dict[str, Any]:
    """Describe coverage without inventing retrieval time."""

    return {
        "source": source,
        "operation": operation,
        "status": status,
        "detail": detail,
        "fetched_at": fetched_at,
    }


def record(
    kind, identity, facts, metrics, findings, social, outcomes
) -> dict[str, Any]:
    """Build the common record shape for every command."""

    return {
        "kind": kind,
        "identity": identity,
        "facts": facts,
        "metrics": metrics,
        "findings": findings,
        "social": social,
        "coverage": outcomes,
        "on_chain": None,
    }


def scan_record(data, provider_data=None, include_raw=False) -> dict[str, Any]:
    """Keep RPC facts and provider measurements in separate sections."""

    summary = data["summary"]
    provider_data = provider_data or {}
    metrics = {
        name: {"source": source, "scope": scope, "values": summary[name]}
        for name, source, scope in (
            ("jupiter", "jupiter", "token"),
            ("rugcheck", "rugcheck", "token"),
            ("stonks_market", "stonks", "pool"),
            ("stonks_holders", "stonks", "token"),
            ("stonks_burns", "stonks", "token"),
            ("stonks_rewards", "stonks", "token"),
            ("reward_comparison", "growr", "token"),
        )
        if name in summary
    }
    facts = {
        name: value for name, value in summary.items() if name not in metrics
    }
    facts["source"] = "rpc"
    if "risk_score" in facts:
        metrics["risk"] = {
            "source": "growr",
            "scope": "token",
            "score": facts.pop("risk_score"),
            "band": facts.pop("risk_band", None),
        }
    outcomes = [coverage("rpc", data["scan_type"], "success")]
    outcomes.extend(
        _provider_coverage(item, provider_data) for item in data["providers"]
    )
    _scan_details(summary, outcomes)
    kind = data["scan_type"]
    identity = {"chain": "solana", "address": data["address"]}
    if kind == "token":
        identity["mint"] = data["address"]
    elif kind == "token_account":
        account = mapping(summary.get("token_account"))
        identity.update(
            {"mint": account.get("mint"), "owner": account.get("owner")}
        )
    result = record(
        kind,
        identity,
        facts,
        metrics,
        data["findings"],
        data.get("social"),
        outcomes,
    )
    if include_raw:
        result["raw"] = {
            source: item.get("data") for source, item in provider_data.items()
        }
    return result


def _provider_coverage(item, provider_data) -> dict[str, Any]:
    """Identify endpoint outcomes without grouping distinct requests."""

    source = item["provider"].lower()
    operation = item.get("operation", "token_context")
    key = (
        source
        if operation == "token_context"
        else "%s_%s" % (source, operation)
    )
    return coverage(
        source,
        operation,
        item["status"],
        item["detail"],
        mapping(provider_data.get(key)).get("fetched_at"),
    )


def _scan_details(summary, outcomes) -> None:
    inventory = mapping(summary.get("token_accounts"))
    for program in ("spl_token", "token_2022"):
        key = "%s_error" % program
        if key in inventory:
            outcomes.append(
                coverage(
                    "rpc",
                    "%s_inventory" % program,
                    "failed",
                    "Inventory read failed",
                )
            )
    if inventory.get("unparsed_account_count", 0):
        outcomes.append(
            coverage(
                "rpc",
                "wallet_inventory_decode",
                "partial",
                "Some returned token-account entries could not be validated",
            )
        )
    metadata = mapping(summary.get("metadata"))
    if metadata:
        status = "partial" if metadata.get("warning") else "success"
        if not metadata.get("exists") and status == "success":
            status = "no_data"
        outcomes.append(
            coverage("rpc", "metadata", status, metadata.get("warning", ""))
        )
    holders = mapping(summary.get("holders"))
    if any(
        item.get("owner") is None for item in holders.get("top_accounts", [])
    ):
        outcomes.append(
            coverage(
                "rpc",
                "holder_owners",
                "partial",
                "Some owners could not be resolved",
            )
        )


def listing_record(
    item, source, fetched_at, include_raw=False
) -> dict[str, Any]:
    """Normalize a discovery record while preserving pool identity."""

    analytics = mapping(item.get("analytics"))
    stonks = source == "stonks"
    identity = {
        "chain": "solana",
        "mint": item.get("mint") if stonks else item.get("id"),
        "pool": item.get("pool") if stonks else None,
        "name": item.get("name"),
        "symbol": item.get("symbol"),
    }
    facts = {
        output: item[key]
        for key, output in (
            ("status", "launch_status"),
            ("createdAt", "created_at"),
            ("graduatedAt", "graduated_at"),
            ("creator", "creator"),
            ("launchpad", "launchpad"),
            ("quoteMint", "quote_mint"),
            ("quoteName", "quote_name"),
            ("quoteSymbol", "quote_symbol"),
            ("quoteCategory", "quote_category"),
            ("graduationProgress", "graduation_progress"),
            ("marketCapUsd", "market_cap_usd"),
            ("volume24hUsd", "volume_24h_usd"),
            ("priceUsd", "price_usd"),
            ("fdvUsd", "fdv_usd"),
            ("peakMarketCapUsd", "peak_market_cap_usd"),
            ("isRewardLaunch", "is_reward_launch"),
            ("quoteOnlyFees", "quote_only_fees"),
            ("metadataUri", "metadata_uri"),
            ("imageUrl", "image_url"),
            ("description", "description"),
            ("url", "provider_url"),
        )
        if key in item
    }
    facts["source"] = source
    outcomes = [
        coverage(source, "discovery", "success", fetched_at=fetched_at)
    ]
    _normalize_listing_text(identity, facts, outcomes)
    for provider in ("jupiter", "on_chain"):
        result = mapping(analytics.get(provider))
        if result:
            outcomes.append(
                coverage(
                    "rpc" if provider == "on_chain" else provider,
                    "token_scan" if provider == "on_chain" else "token_lookup",
                    result["status"],
                    result.get("detail", ""),
                    result.get("fetched_at"),
                )
            )
    result = record(
        "pool" if stonks else "token_discovery",
        identity,
        facts,
        analytics.get("metrics", {}),
        [],
        analytics.get("social"),
        outcomes,
    )
    on_chain = mapping(analytics.get("on_chain"))
    if on_chain.get("status") == "success" and on_chain.get("data"):
        result["on_chain"] = scan_record(
            on_chain["data"], include_raw=include_raw
        )
    if include_raw:
        result["raw"] = {
            provider: mapping(analytics.get(provider)).get("data")
            for provider in ("jupiter",)
            if provider in analytics
        }
    return result


def _normalize_listing_text(identity, facts, outcomes) -> None:
    """Normalize invalid text and report incomplete evidence."""

    text_fields = (
        "launch_status",
        "created_at",
        "graduated_at",
        "creator",
        "launchpad",
        "quote_mint",
        "quote_name",
        "quote_symbol",
        "quote_category",
        "metadata_uri",
        "image_url",
        "description",
        "provider_url",
    )
    for section, keys in ((identity, list(identity)), (facts, text_fields)):
        for key in keys:
            value = section.get(key)
            if value is not None and not isinstance(value, str):
                section[key] = None
                outcomes.append(
                    coverage(
                        "growr",
                        "normalization",
                        "partial",
                        "Invalid text field replaced with null: %s" % key,
                    )
                )


def report_records(
    report, include_raw=False
) -> tuple[list[dict[str, Any]], Any, list[dict[str, Any]]]:
    """Return records, pagination, and discovery coverage."""

    if isinstance(report, ScanReport):
        return (
            [scan_record(report.to_dict(), report.provider_data, include_raw)],
            None,
            [],
        )
    findings = report.findings
    stonks = findings.source == "stonk"
    source = "stonks" if stonks else findings.source
    envelope = mapping(findings.tokens)
    items = envelope.get("pools", []) if stonks else findings.tokens

    fetched_at = datetime.fromtimestamp(
        findings.timestamp, timezone.utc
    ).isoformat()
    records = [
        listing_record(item, source, fetched_at, include_raw) for item in items
    ]
    return (
        records,
        envelope.get("pagination"),
        []
        if records
        else [
            coverage(
                source, "discovery", findings.status, fetched_at=fetched_at
            )
        ],
    )
