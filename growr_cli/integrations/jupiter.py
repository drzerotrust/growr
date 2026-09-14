"""Jupiter endpoints and response interpretation."""

from __future__ import annotations

from typing import Any

from solders.pubkey import Pubkey

from growr_cli import settings
from growr_cli.analysis.metrics import mapping, metric, number
from growr_cli.integrations.http import provider_result
from growr_cli.models import (
    ActivitySnapshot,
    EnrichmentResult,
    ProviderSnapshot,
)

JUPITER_CATEGORIES = ("toporganicscore", "toptraded", "toptrending")
JUPITER_INTERVALS = ("5m", "1h", "6h", "24h")


class JupiterClient:
    """Read jupiter data without owning workflow decisions."""

    def __init__(self, http, api_key) -> None:
        """Store the transport and optional Jupiter credential."""

        self.http = http
        self.jupiter_api_key = api_key

    def _get_single(self, mint) -> tuple[dict[str, Any] | None, str | None]:
        """Fetch Jupiter enrichment when an API key is configured.

        The search API can return nearby or partial matches. Only a
        record whose mint identifier equals the requested mint is
        accepted.

        Args:
            mint: Token mint address.

        Returns:
            ``(token, None)`` when a matching record is found, ``(None,
            error)`` on transport failure, or ``(None, None)`` when
            nothing matched.
        """

        if not self.jupiter_api_key:
            return None, "Jupiter API key is not configured"

        url = "%s/search" % settings.JUPITER_API_URL
        headers = {"x-api-key": self.jupiter_api_key}
        data, error = self.http.get_json(
            url, params={"query": mint}, headers=headers
        )
        if error:
            return None, error
        if not isinstance(data, list) or any(
            not isinstance(item, dict) for item in data
        ):
            return None, "Jupiter returned an unexpected response shape"

        for item in data:
            if isinstance(item, dict) and self._jupiter_item_matches(
                item, mint
            ):
                return item, None
        return None, None

    def _jupiter_item_matches(self, item, mint) -> bool:
        # The documented id wins over compatibility aliases. A nearby
        # result cannot override a conflicting mint identifier.
        identifier = item.get("id", item.get("address", item.get("mint")))
        return identifier == mint

    def discover(
        self, mode="recent", *, query=None, interval=None, limit=None
    ) -> list[dict[str, Any]]:
        """Fetch one discovery response with validated options."""

        if not self.jupiter_api_key:
            raise ValueError("Jupiter discovery requires JUPITER_API_KEY")
        path, params = discovery_request(mode, query, interval, limit)
        data, error = self.http.get_records(
            "%s/%s" % (settings.JUPITER_API_URL, path),
            params=params,
            headers={"x-api-key": self.jupiter_api_key},
            source="Jupiter",
        )
        if error:
            raise ValueError(error)
        return data

    def get_token(self, mint) -> EnrichmentResult:
        """Return single-token data with explicit coverage."""

        data, error = self._get_single(mint)
        if error == "Jupiter API key is not configured":
            return provider_result("not_configured", detail=error)
        if error:
            return provider_result("failed", detail=error)
        return provider_result("success" if data else "no_data", data)

    def get_tokens(self, mints) -> dict[str, EnrichmentResult]:
        """Fetch exact mint matches in batches of at most 100."""

        unique_mints = list(dict.fromkeys(mints))
        results = {}
        for offset in range(0, len(unique_mints), 100):
            batch = unique_mints[offset : offset + 100]
            results.update(self._get_batch(batch))
        return results

    def _get_batch(self, mints) -> dict[str, EnrichmentResult]:
        """Retain a result for every mint, including failures."""

        if not self.jupiter_api_key:
            return {
                mint: provider_result(
                    "not_configured",
                    detail="Jupiter API key is not configured",
                )
                for mint in mints
            }
        records, error = self.http.get_records(
            "%s/search" % settings.JUPITER_API_URL,
            params={"query": ",".join(mints)},
            headers={"x-api-key": self.jupiter_api_key},
        )
        if error:
            return {
                mint: provider_result("failed", detail=error) for mint in mints
            }

        results = {}
        for mint in mints:
            # Batch lookup requires id; single lookup accepts aliases.
            matches = [item for item in records if item.get("id") == mint]
            data = matches[0] if matches else None
            results[mint] = provider_result(
                "success" if matches else "no_data",
                data,
                "Record found"
                if matches
                else "No indexed record for this mint",
            )
        return results


def token_summary(token) -> dict[str, Any]:
    """Normalize provider-reported Jupiter fields."""

    return {
        "name": token.get("name"),
        "symbol": token.get("symbol"),
        "price_usd": token.get("usdPrice"),
        "market_cap": token.get("mcap"),
        "liquidity": token.get("liquidity"),
        "holder_count": token.get("holderCount"),
        "verified": token.get("isVerified"),
        "launchpad": token.get("launchpad"),
        "fdv_usd": token.get("fdv"),
        "organic_score": token.get("organicScore"),
        "organic_score_label": token.get("organicScoreLabel"),
        "developer": token.get("dev"),
        "token_program": token.get("tokenProgram"),
        "total_supply": token.get("totalSupply"),
        "circulating_supply": token.get("circSupply"),
        "first_pool": mapping(token.get("firstPool")),
        "audit": mapping(token.get("audit")),
        "activity": {
            interval: mapping(token.get("stats%s" % interval))
            for interval in JUPITER_INTERVALS
        },
        "updated_at": token.get("updatedAt"),
        "price_block_id": token.get("priceBlockId"),
    }


def snapshot(token) -> ProviderSnapshot:
    """Translate Jupiter fields into the internal metric contract."""

    market = {
        "price_usd": token.get("usdPrice"),
        "market_cap_usd": token.get("mcap"),
        "fdv_usd": token.get("fdv"),
        "token_liquidity_usd": metric(
            number(token.get("liquidity")), "jupiter"
        ),
    }
    risk = {
        key: metric(token.get(key), "jupiter")
        for key in (
            "holderCount",
            "dev",
            "organicScore",
            "organicScoreLabel",
            "isVerified",
            "tokenProgram",
            "totalSupply",
            "circSupply",
        )
    }
    risk["audit"] = {
        key: metric(value, "jupiter")
        for key, value in mapping(token.get("audit")).items()
    }
    activity = {}
    for interval in ("5m", "1h", "6h", "24h"):
        stats = mapping(token.get("stats%s" % interval))
        activity[interval] = ActivitySnapshot(
            {key: metric(value, "jupiter") for key, value in stats.items()},
            number(stats.get("buyVolume")),
            number(stats.get("sellVolume")),
        )
    return ProviderSnapshot("jupiter", market, risk, activity)


def social_links(token) -> list[dict[str, Any]]:
    """Collect project links for shared validation and scoring."""

    return [
        {
            "url": token.get(field),
            "kind": "website" if field == "website" else "social",
            "source": "jupiter",
        }
        for field in (
            "website",
            "twitter",
            "telegram",
            "discord",
            "instagram",
            "tiktok",
        )
        if token.get(field)
    ]


def discovery_request(
    mode, query, interval, limit
) -> tuple[str, dict[str, Any]]:
    """Validate feed-specific options before constructing a request."""

    if mode == "search":
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Jupiter search requires a nonempty query")
        if interval is not None or limit is not None:
            raise ValueError("--interval and --limit require a ranked feed")
        mint_queries(query)
        return "search", {"query": query.strip()}
    if query is not None:
        raise ValueError("A query cannot be combined with a Jupiter feed")
    if mode == "recent":
        if interval is not None or limit is not None:
            raise ValueError("--interval and --limit require a ranked feed")
        return "recent", {}
    if mode not in JUPITER_CATEGORIES:
        raise ValueError("Unsupported Jupiter discovery mode")
    interval = interval or "24h"
    limit = 50 if limit is None else limit
    if interval not in JUPITER_INTERVALS:
        raise ValueError("Unsupported Jupiter interval")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Jupiter --limit must be between 1 and 100")
    return "%s/%s" % (mode, interval), {"limit": limit}


def mint_queries(query) -> set[str] | None:
    """Distinguish exact mint queries from names and symbols."""

    if query is None:
        return None
    parts = [part.strip() for part in query.split(",")]
    if len(parts) > 100:
        raise ValueError("Jupiter search accepts at most 100 mint addresses")
    try:
        for part in parts:
            Pubkey.from_string(part)
    except ValueError:
        if len(parts) > 1:
            raise ValueError(
                "Comma-separated queries must be mint addresses"
            ) from None
        return None
    return set(parts)
