"""Stonks discovery workflow and report construction."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from growr_cli.enrichment.social import attach_social
from growr_cli.integrations.stonks import (
    listing_data,
    query_metrics,
    social_links,
)
from growr_cli.logger import get_logger
from growr_cli.models import SearchReport, TokenSearches

LOGGER = get_logger(__name__)


class StonksSearcher:
    """Discover one page using an injected Stonks integration."""

    def __init__(self, client) -> None:
        """Keep HTTP ownership in the composition layer."""

        self.client = client

    def search(
        self,
        mode="recent",
        *,
        page=1,
        page_size=30,
        category=None,
    ) -> SearchReport:
        """Fetch one discovery envelope with explicit search options."""

        if category is not None:
            LOGGER.info("Filtering Stonks category: %s", category)
        LOGGER.info("Fetching Stonks discovery: %s", mode)
        tokens = self.client.get_pools(
            mode, page=page, page_size=page_size, category=category
        )
        return self._report(tokens, "stonk-%s" % mode)

    def search_query(
        self, query, *, sort="marketCap", page=1, page_size=30
    ) -> SearchReport:
        """Return one candidate page without enrichment requests."""

        LOGGER.info("Searching Stonks public tokens")
        tokens = self.client.search_pools(
            query, sort=sort, page=page, page_size=page_size
        )
        report = self._report(tokens, "stonk-search")
        # SearchReport preserves raw data before analytics are attached.
        # Keep server ordering, separate pools and pagination intact.
        tokens = report.findings.tokens
        if not isinstance(tokens, dict):
            raise ValueError("Stonks query requires a pool envelope")
        report.findings.tokens = {
            **tokens,
            "pools": [self._query_pool(pool) for pool in tokens["pools"]],
        }
        return report

    def _query_pool(self, pool) -> dict[str, Any]:
        """Normalize fetched fields and discard untrusted analytics."""

        item = deepcopy(pool)
        item.pop("analytics", None)
        item = attach_social(item, social_links(pool), {"stonks": "success"})
        item["analytics"]["metrics"] = {"market": query_metrics(pool)}
        return item

    def _report(self, tokens, mode) -> SearchReport:
        """Record coverage and the untouched discovery envelope."""

        envelope = tokens
        tokens = listing_data(envelope)
        pools = tokens["pools"]
        LOGGER.info("Stonks returned %d pools", len(pools))
        findings = TokenSearches(
            tokens,
            datetime.now(timezone.utc).timestamp(),
            "stonk",
            "success" if pools else "no_data",
        )
        report = SearchReport(mode, findings)
        report.raw = deepcopy(envelope)
        return report
