"""Dexscreener feed selection and discovery report construction."""

from copy import deepcopy
from datetime import datetime, timezone

from growr_cli.enrichment.social import attach_social
from growr_cli.integrations.dexscreener import social_links
from growr_cli.logger import get_logger
from growr_cli.models import SearchReport, TokenSearches

LOGGER = get_logger(__name__)


class DexscreenerTokenSearcher:
    """Discover Solana tokens from boosts and community takeovers."""

    def __init__(self, client) -> None:
        """Keep HTTP ownership in the composition layer."""

        self.client = client

    def search(
        self, *, boosted=False, community_takeovers=False
    ) -> SearchReport:
        """Retain boost precedence when both feed flags are selected."""

        if boosted:
            search_type = "boosted"
        elif community_takeovers:
            search_type = "community-takeovers"
        else:
            raise ValueError("Select --boosted or --community-takeovers")

        LOGGER.info("Fetching Dexscreener discovery: %s", search_type)
        raw_tokens = self.client.discover(search_type)

        # Both feeds span chains; only Solana records enter enrichment.
        tokens = [
            attach_social(
                token,
                social_links(token, discovery=True),
                {"dexscreener": "success"},
            )
            for token in raw_tokens
            if token.get("chainId") == "solana"
        ]
        LOGGER.info("Dexscreener returned %d Solana tokens", len(tokens))
        report = SearchReport(
            search_type,
            TokenSearches(
                tokens,
                datetime.now(timezone.utc).timestamp(),
                "dexscreener",
                "success" if tokens else "no_data",
            ),
        )
        report.raw = deepcopy(raw_tokens)
        return report
