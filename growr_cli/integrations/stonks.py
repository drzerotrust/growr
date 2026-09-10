"""Stonks endpoints, categories, and pool validation."""

from __future__ import annotations

from typing import Any

from solders.pubkey import Pubkey

from growr_cli import settings
from growr_cli.analysis.metrics import metric, number
from growr_cli.models import ProviderSnapshot

STONKS_CATEGORIES = (
    "xstock",
    "prestock",
    "custom",
    "collectibles",
    "currencies",
    "leverage",
)


class StonksClient:
    """Fetch validated pool envelopes without enrichment."""

    def __init__(self, http) -> None:
        """Use the injected transport; its creator owns cleanup."""

        self.http = http

    def get_pools(
        self,
        mode="recent",
        *,
        page=1,
        page_size=30,
        category=None,
    ) -> dict[str, Any]:
        """Select the endpoint and translate options to query fields."""

        if mode == "recent":
            if category is not None:
                raise ValueError("Recent launches do not support category")
            return self._get_pools("recent-launches")
        if mode not in {"marketCap", "volume"}:
            raise ValueError("Unsupported Stonks search mode")
        filters = {"category": category} if category is not None else {}
        return self._get_pools(
            "platform-pools",
            {"sort": mode, "page": page, "pageSize": page_size, **filters},
        )

    def _get_pools(self, endpoint, params=None) -> dict[str, Any]:
        """Validate every mint while preserving the server envelope."""

        tokens, error = self.http.get_json(
            f"{settings.STONKS_API_URL}/{endpoint}",
            params=params,
            source="Stonks",
        )
        if error:
            raise ValueError(error)
        if not isinstance(tokens, dict) or not isinstance(
            tokens.get("pools"), list
        ):
            raise ValueError("Stonks returned an unexpected response shape")
        pools = tokens["pools"]
        for pool in pools:
            if not isinstance(pool, dict) or not isinstance(
                pool.get("mint"), str
            ):
                raise ValueError(
                    "Stonks returned a pool without a mint address"
                )
            try:
                Pubkey.from_string(pool["mint"])
            except ValueError:
                raise ValueError(
                    "Stonks returned an invalid mint address"
                ) from None
        return tokens


def snapshot(launch) -> ProviderSnapshot:
    """Translate fallbacks and retain the discovery record."""

    return ProviderSnapshot(
        "stonks",
        {
            "price_usd": launch.get("priceUsd"),
            "market_cap_usd": launch.get("marketCapUsd"),
            "fdv_usd": launch.get("fdvUsd"),
            "stonks_volume_24h_usd": metric(
                number(launch.get("volume24hUsd")), "stonks", "pool"
            ),
        },
        {
            "transfer_tax_bps": metric(
                number(launch.get("transferTaxBps")), "stonks"
            )
        },
    )


def social_links(launch) -> list[dict[str, Any]]:
    """Extract explicit project links from Stonks discovery fields."""

    return [
        {"url": launch.get(field), "kind": kind, "source": "stonks"}
        for field, kind in (
            ("website", "website"),
            ("twitter", "social"),
            ("telegram", "social"),
        )
    ]
