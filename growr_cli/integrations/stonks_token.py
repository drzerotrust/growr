"""Stonkfun single-mint endpoints and field translation."""

from typing import Any

from growr_cli import settings
from growr_cli.integrations.http import provider_result
from growr_cli.integrations.stonks_api import error_code, fetch, token_fields
from growr_cli.integrations.stonks_rewards import get_rewards
from growr_cli.models import EnrichmentResult


def _records(data, key) -> bool:
    records = data.get(key)
    return isinstance(records, list) and all(
        isinstance(item, dict) for item in records
    )


def _burn_record(item, mint) -> bool:
    """Keep token base units as decimal strings without coercion."""

    if not isinstance(item, dict) or item.get("mint", mint) != mint:
        return False
    raw = item.get("amountRaw")
    return raw is None or (
        isinstance(raw, str) and raw.isascii() and raw.isdecimal()
    )


class StonksTokenClient:
    """Read a mint's market data, reported holders and burn history."""

    def __init__(self, http) -> None:
        """Borrow the transport owned by the CLI."""

        self.http = http

    def _invalid(self, data) -> EnrichmentResult:
        return provider_result(
            "failed", data, "Stonks returned an unexpected response shape"
        )

    def get_market(self, mint) -> EnrichmentResult:
        """Retain the envelope and require an exact mint match."""

        data, error = fetch(self.http, "tokens/%s" % mint)
        if error:
            status = "no_data" if error_code(data) == "not_found" else "failed"
            return provider_result(status, data, error)
        token = data["data"].get("token")
        if not isinstance(token, dict) or token.get("mint") != mint:
            return self._invalid(data)
        try:
            token_fields(token)
        except ValueError:
            return self._invalid(data)
        return provider_result(
            "success", data, "Matching platform token found"
        )

    def get_rewards(self, mint) -> EnrichmentResult:
        """Read reward totals using the dedicated field translator."""

        return get_rewards(self.http, mint)

    def get_holders(self, mint) -> EnrichmentResult:
        """Keep unavailable and incomplete holder snapshots visible."""

        # The public v1 API does not expose live holder snapshots.
        data, error = self.http.get_json(
            settings.STONKS_HOLDERS_API_URL,
            params={"mint": mint},
            source="Stonks",
        )
        if error:
            return provider_result("failed", data, error)
        if not isinstance(data, dict):
            return self._invalid(data)
        if data.get("mint") != mint or not isinstance(
            data.get("available"), bool
        ):
            return self._invalid(data)
        result = provider_result("success", data)
        if not data["available"]:
            result.status = "failed"
            result.detail = "Stonks holder data is unavailable"
            return result
        if (
            not isinstance(data.get("complete"), bool)
            or not _records(data, "holders")
            or any(
                not isinstance(holder.get("address"), str)
                for holder in data["holders"]
            )
        ):
            return self._invalid(data)
        result.status = "success" if data["complete"] else "partial"
        result.detail = (
            "Stonks reports holder data as complete"
            if data["complete"]
            else "Stonks holder snapshot is incomplete"
        )
        return result

    def get_burns(self, mint) -> EnrichmentResult:
        """Validate the total and recent burns for this mint."""

        envelope, error = fetch(self.http, "tokens/%s/burns" % mint)
        if error:
            return provider_result("failed", envelope, error)
        data = envelope["data"]
        if (
            data.get("mint") != mint
            or "totals" not in data
            or not _records(data, "burns")
        ):
            return self._invalid(envelope)
        totals = data["totals"]
        entries = [totals] if totals is not None else []
        entries.extend(data["burns"])
        if not all(_burn_record(item, mint) for item in entries):
            return self._invalid(envelope)
        status = "success" if entries else "no_data"
        detail = (
            "Provider-reported burn history"
            if entries
            else "No Stonks burn data for this mint"
        )
        return provider_result(status, envelope, detail)


def market_summary(data, mint) -> dict[str, Any]:
    """Translate the exact token while preserving the pool contract."""

    pools = [token_fields(data["data"]["token"])]
    fields = {
        "mint": "mint",
        "name": "name",
        "symbol": "symbol",
        "pool": "pool",
        "status": "status",
        "priceUsd": "price_usd",
        "marketCapUsd": "market_cap_usd",
        "peakMarketCapUsd": "peak_market_cap_usd",
        "fdvUsd": "fdv_usd",
        "volume24hUsd": "volume_24h_usd",
        "priceChange24h": "price_change_24h",
        "createdAt": "created_at",
        "graduatedAt": "graduated_at",
        "graduationProgress": "graduation_progress",
        "quoteMint": "quote_mint",
        "quoteName": "quote_name",
        "quoteSymbol": "quote_symbol",
        "quoteCategory": "quote_category",
        "creator": "creator",
        "launchpad": "launchpad",
        "metadataUri": "metadata_uri",
        "imageUrl": "image_url",
        "quoteOnlyFees": "quote_only_fees",
        "isRewardLaunch": "is_reward_launch",
        "mode": "mode",
        "transferTaxBps": "transfer_tax_bps",
    }
    normalized = [_translate(pool, fields) for pool in pools]
    return {**normalized[0], "pool_count": len(pools), "pools": normalized}


def holders_summary(data, mint) -> dict[str, Any]:
    """Keep reported holder addresses separate from RPC accounts."""

    summary = _translate(
        data,
        {
            "mint": "mint",
            "decimals": "decimals",
            "supplyTokens": "supply_tokens",
            "available": "available",
            "complete": "complete",
            "holderCount": "holder_count",
        },
    )
    summary["holders"] = [
        _translate(
            holder,
            {
                "rank": "rank",
                "address": "address",
                "amountTokens": "amount_tokens",
                "supplyPct": "supply_percent",
            },
        )
        for holder in data["holders"]
    ]
    return summary


def burns_summary(data, mint) -> dict[str, Any]:
    """Keep v1 totals separate from its limited recent-burn page."""

    data = data["data"]
    fields = {
        "mint": "mint",
        "symbol": "symbol",
        "decimals": "decimals",
        "amountRaw": "raw_amount",
        "amountTokens": "amount_tokens",
        "valueUsdAtBurn": "value_usd_at_burn",
        "burnCount": "burn_count",
        "lastBurnAt": "last_burn_at",
        "signature": "signature",
        "priceUsd": "price_usd_at_burn",
        "valueUsd": "value_usd_at_burn",
        "source": "source",
        "burnedAt": "created_at",
    }
    # V1 provides one total. Do not invent the legacy buyback/reward
    # breakdown or infer base units from floating token amounts.
    summary = (
        {"totals": _translate(data["totals"], fields)}
        if data["totals"] is not None
        else {}
    )
    return {
        **summary,
        "recent": [_translate(item, fields) for item in data["burns"]],
    }


def _translate(data, fields) -> dict[str, Any]:
    return {output: data[key] for key, output in fields.items() if key in data}
