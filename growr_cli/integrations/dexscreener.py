"""Dexscreener endpoints and response interpretation."""

from __future__ import annotations

from typing import Any

from growr_cli import settings
from growr_cli.analysis.metrics import mapping, metric, number
from growr_cli.integrations.http import provider_result
from growr_cli.models import (
    ActivitySnapshot,
    EnrichmentResult,
    PoolSnapshot,
    ProviderSnapshot,
)


class DexscreenerClient:
    """Read dexscreener data without owning workflow decisions."""

    def __init__(self, http) -> None:
        """Use the injected transport; its creator owns cleanup."""

        self.http = http

    def _get_single(self, mint) -> tuple[list[dict[str, Any]], str | None]:
        """Get Dexscreener market pairs and choose later in the scanner.

        Args:
            mint: Token mint address.

        Returns:
            Solana pairs plus an optional error string.
        """

        url = f"{settings.DEXSCREENER_API_URL}/tokens/{mint}"
        data, error = self.http.get_json(url)
        if error:
            return [], error
        if not isinstance(data, dict) or "pairs" not in data:
            return [], "Dexscreener returned an unexpected response shape"

        pairs = data.get("pairs")
        if pairs is None:
            return [], None
        if not isinstance(pairs, list) or any(
            not isinstance(pair, dict) for pair in pairs
        ):
            return [], "Dexscreener returned an unexpected response shape"

        valid_pairs = []
        for pair in pairs:
            if isinstance(pair, dict) and pair.get("chainId") == "solana":
                valid_pairs.append(pair)
        return valid_pairs, None

    def get_pairs(self, mint) -> EnrichmentResult:
        """Return single-token data with explicit coverage."""

        data, error = self._get_single(mint)
        if error:
            return provider_result("failed", detail=error)
        return provider_result("success" if data else "no_data", data)

    def get_tokens(self, mints) -> dict[str, EnrichmentResult]:
        """Fetch exact mint matches in batches of at most 30."""

        unique_mints = list(dict.fromkeys(mints))
        results = {}
        for offset in range(0, len(unique_mints), 30):
            batch = unique_mints[offset : offset + 30]
            results.update(self._get_batch(batch))
        return results

    def _get_batch(self, mints) -> dict[str, EnrichmentResult]:
        """Retain a result for every mint, including failures."""

        mint_query = ",".join(mints)
        records, error = self.http.get_records(
            f"{settings.DEXSCREENER_V1_API_URL}/tokens/v1/solana/{mint_query}"
        )
        if error:
            return {
                mint: provider_result("failed", detail=error) for mint in mints
            }

        results = {}
        for mint in mints:
            matches = [item for item in records if self._matches(item, mint)]
            data = matches
            results[mint] = provider_result(
                "success" if matches else "no_data",
                data,
                "Record found"
                if matches
                else "No indexed record for this mint",
            )
        return results

    def _matches(self, item, mint) -> bool:
        """Match the exact Solana base mint in batch results."""

        base = item.get("baseToken")
        return (
            item.get("chainId") == "solana"
            and isinstance(base, dict)
            and base.get("address") == mint
        )

    def discover(self, feed) -> list[dict[str, Any]]:
        """Read a discovery feed from the API root, not /latest/dex."""

        endpoints = {
            "boosted": "token-boosts/latest/v1",
            "community-takeovers": "community-takeovers/latest/v1",
        }
        if feed not in endpoints:
            raise ValueError("Unsupported Dexscreener discovery feed")
        endpoint = endpoints[feed]
        records, error = self.http.get_records(
            f"{settings.DEXSCREENER_V1_API_URL}/{endpoint}",
            source="Dexscreener",
        )
        if error:
            raise ValueError(error)
        return records


def pair_summary(pair) -> dict[str, Any]:
    """Keep only the market fields that are useful in a terminal."""

    liquidity = pair.get("liquidity")
    liquidity_usd = (
        liquidity.get("usd") if isinstance(liquidity, dict) else None
    )
    volume = pair.get("volume")
    volume_24h = volume.get("h24") if isinstance(volume, dict) else None
    return {
        "dex": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "price_usd": pair.get("priceUsd"),
        "liquidity_usd": liquidity_usd,
        "market_cap": pair.get("marketCap"),
        "fdv": pair.get("fdv"),
        "volume_24h": volume_24h,
        "pair_created_at": pair.get("pairCreatedAt"),
        "url": pair.get("url"),
    }


def pool_snapshot(pair) -> PoolSnapshot:
    """Translate pair identity and retain raw liquidity values."""

    return PoolSnapshot(
        pair.get("pairAddress", ""),
        pair.get("chainId"),
        mapping(pair.get("baseToken")).get("address"),
        mapping(pair.get("liquidity")).get("usd"),
        pair,
    )


def snapshot(pair) -> ProviderSnapshot:
    """Translate selected-pool metrics while retaining pool scope."""

    market = {
        "price_usd": pair.get("priceUsd"),
        "market_cap_usd": pair.get("marketCap"),
        "fdv_usd": pair.get("fdv"),
        "pool_liquidity_usd": metric(
            number(mapping(pair.get("liquidity")).get("usd")),
            "dexscreener",
            "pool",
        ),
    }
    activity = {}
    for interval, key in (
        ("5m", "m5"),
        ("1h", "h1"),
        ("6h", "h6"),
        ("24h", "h24"),
    ):
        stats = {
            "priceChange": mapping(pair.get("priceChange")).get(key),
            "volume": mapping(pair.get("volume")).get(key),
            **mapping(mapping(pair.get("txns")).get(key)),
        }
        activity[interval] = ActivitySnapshot(
            {
                name: metric(value, "dexscreener", "pool")
                for name, value in stats.items()
            }
        )
    return ProviderSnapshot("dexscreener", market, {}, activity)


def social_links(record, *, discovery=False) -> list[dict[str, Any]]:
    """Extract project links, excluding the provider's chart URL."""

    if discovery:
        return _link_candidates(record.get("links"), None)
    info = mapping(record.get("info"))
    return [
        *_link_candidates(info.get("websites"), "website"),
        *_link_candidates(info.get("socials"), "social"),
    ]


def _link_candidates(records, kind) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    candidates = []
    for record in records:
        if not isinstance(record, dict):
            continue
        label = str(record.get("label", "")).lower()
        link_type = str(record.get("type") or "").lower()
        website = label == "website" or link_type == "website"
        candidates.append(
            {
                "url": record.get("url"),
                "kind": kind or ("website" if website else "social"),
                "source": "dexscreener",
            }
        )
    return candidates
