"""Stonks discovery workflow and report construction."""

from datetime import datetime, timezone

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
        pools = tokens["pools"]
        LOGGER.info("Stonks returned %d pools", len(pools))
        findings = TokenSearches(
            tokens,
            datetime.now(timezone.utc).timestamp(),
            "stonk",
            "success" if pools else "no_data",
        )
        return SearchReport(f"stonk-{mode}", findings)
