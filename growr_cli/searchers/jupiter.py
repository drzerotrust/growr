"""Jupiter discovery with token metrics and reported social presence."""

from copy import deepcopy
from datetime import datetime, timezone

from growr_cli.enrichment.social import attach_social
from growr_cli.integrations.jupiter import (
    mint_queries,
    social_links,
    token_summary,
)
from growr_cli.logger import get_logger
from growr_cli.models import SearchReport, TokenSearches

LOGGER = get_logger(__name__)


class JupiterTokenSearcher:
    """Normalize one Solana discovery response."""

    def __init__(self, client) -> None:
        """Borrow a Jupiter client from the CLI."""

        self.client = client

    def search(
        self, mode="recent", *, query=None, interval=None, limit=None
    ) -> SearchReport:
        """Retain discovery order, raw data and exact mint matches."""

        LOGGER.info("Fetching Jupiter discovery: %s", mode)
        raw = self.client.discover(
            mode, query=query, interval=interval, limit=limit
        )
        requested = mint_queries(query)
        tokens = []
        for token in raw:
            # Symbol searches retain candidates. Mint queries must not
            # attach another token's evidence to the requested address.
            identifier = token.get("id")
            if requested is not None and (
                not isinstance(identifier, str) or identifier not in requested
            ):
                continue
            # Analytics is growr-owned evidence. Preserve unexpected
            # provider fields in raw output without trusting them here.
            item = deepcopy(token)
            item.pop("analytics", None)
            item = attach_social(
                item, social_links(token), {"jupiter": "success"}
            )
            item["analytics"]["metrics"] = {
                "jupiter": {
                    "source": "jupiter",
                    "scope": "token",
                    "values": token_summary(token),
                }
            }
            tokens.append(item)
        LOGGER.info("Jupiter returned %d matching tokens", len(tokens))
        report = SearchReport(
            mode,
            TokenSearches(
                tokens,
                datetime.now(timezone.utc).timestamp(),
                "jupiter",
                "success" if tokens else "no_data",
            ),
        )
        report.raw = deepcopy(raw)
        return report
