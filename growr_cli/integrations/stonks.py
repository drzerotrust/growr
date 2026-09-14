"""Stonks endpoints, categories, and pool validation."""

from __future__ import annotations

from typing import Any

from solders.pubkey import Pubkey

from growr_cli.analysis.metrics import metric, number
from growr_cli.integrations.http import ProviderError
from growr_cli.integrations.stonks_api import fetch, token_fields
from growr_cli.models import ProviderSnapshot

STONKS_CATEGORIES = (
    "xstock",
    "prestock",
    "custom",
    "collectibles",
    "currencies",
    "leverage",
)
STONKS_SORTS = ("marketCap", "volume", "newest")


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

        if mode not in ("recent", "marketCap", "volume"):
            raise ValueError("Unsupported Stonks listing mode")
        sort = "newest" if mode == "recent" else mode
        params = listing_parameters(sort, page, page_size, category)
        return self._get_pools(params)

    def search_pools(
        self, query, *, sort="marketCap", page=1, page_size=30
    ) -> dict[str, Any]:
        """Fetch one server-filtered page with the q parameter."""

        params = query_parameters(query, sort, page, page_size)
        return self._get_pools(params)

    def _get_pools(self, params) -> dict[str, Any]:
        """Validate v1 data while retaining the untouched envelope."""

        envelope, error = fetch(self.http, "tokens", params)
        if error:
            raise ProviderError(error)
        listing_data(envelope)
        return envelope


def listing_data(envelope) -> dict[str, Any]:
    """Unpack v1 tokens for workflows that consume pool records."""

    data = envelope.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("tokens"), list):
        raise ValueError("Stonks returned an unexpected response shape")
    pools = []
    for token in data["tokens"]:
        if not isinstance(token, dict) or not isinstance(
            token.get("mint"), str
        ):
            raise ValueError("Stonks returned a token without a mint address")
        try:
            Pubkey.from_string(token["mint"])
        except ValueError:
            raise ValueError(
                "Stonks returned an invalid mint address"
            ) from None
        pools.append(token_fields(token))
    # Keep pagination and metadata outside the result list.
    return {**data, "pools": pools, "meta": envelope.get("meta")}


def listing_parameters(
    sort="newest", page=1, page_size=30, category=None
) -> dict[str, Any]:
    """Enforce the public API's sorting and pagination bounds."""

    if sort not in STONKS_SORTS:
        raise ValueError("Stonks --sort must be marketCap, volume or newest")
    for name, value in (("--page", page), ("--page-size", page_size)):
        if type(value) is not int or value < 1:
            raise ValueError("Stonks %s must be a positive integer" % name)
    if page_size > 100:
        raise ValueError("Stonks --page-size must be between 1 and 100")
    if category is not None and category not in STONKS_CATEGORIES:
        raise ValueError("Unsupported Stonks category")
    filters = {"category": category} if category is not None else {}
    return {"sort": sort, "page": page, "pageSize": page_size, **filters}


def query_parameters(
    query, sort=None, page=None, page_size=None
) -> dict[str, Any]:
    """Validate text and pagination before any provider request."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Stonks search requires a nonempty query")
    sort = "marketCap" if sort is None else sort
    page = 1 if page is None else page
    page_size = 30 if page_size is None else page_size
    return {
        "q": query.strip(),
        **listing_parameters(sort, page, page_size),
    }


def query_metrics(pool) -> dict[str, Any]:
    """Attribute available search measurements to their Stonks pool."""

    return {
        output: metric(number(pool.get(field)), "stonks", "pool")
        for field, output in (
            ("priceUsd", "price_usd"),
            ("marketCapUsd", "market_cap_usd"),
            ("fdvUsd", "fdv_usd"),
            ("volume24hUsd", "stonks_volume_24h_usd"),
        )
    }


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
