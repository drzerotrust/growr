"""Jupiter endpoints and response interpretation."""

from __future__ import annotations

from typing import Any

from growr_cli import settings
from growr_cli.analysis.metrics import mapping, metric, number
from growr_cli.integrations.http import provider_result
from growr_cli.models import (
    ActivitySnapshot,
    EnrichmentResult,
    ProviderSnapshot,
)


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

        url = f"{settings.JUPITER_API_URL}/search"
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
        return any(
            item.get(field) == mint for field in ("id", "address", "mint")
        )

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
            f"{settings.JUPITER_API_URL}/search",
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
        stats = mapping(token.get(f"stats{interval}"))
        activity[interval] = ActivitySnapshot(
            {key: metric(value, "jupiter") for key, value in stats.items()},
            number(stats.get("buyVolume")),
            number(stats.get("sellVolume")),
        )
    return ProviderSnapshot("jupiter", market, risk, activity)
