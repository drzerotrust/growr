"""Join discovery records with provider and RPC snapshots."""

from collections import Counter
from dataclasses import asdict

from growr_cli.analysis.market import combine_metrics
from growr_cli.analysis.metrics import mapping
from growr_cli.enrichment.on_chain import OnChainEnricher
from growr_cli.enrichment.social import attach_social
from growr_cli.integrations.jupiter import snapshot as jupiter_snapshot
from growr_cli.integrations.jupiter import social_links as jupiter_links
from growr_cli.integrations.stonks import snapshot as stonks_snapshot
from growr_cli.integrations.stonks import social_links as stonks_links
from growr_cli.logger import get_logger
from growr_cli.models import SearchReport

LOGGER = get_logger(__name__)


def _log_coverage(provider, results) -> None:
    """Summarize coverage once for the entire provider phase."""

    counts = Counter(result.status for result in results.values())
    summary = ", ".join(
        "%s=%s" % (status, count) for status, count in sorted(counts.items())
    )
    log = LOGGER.warning if counts["failed"] else LOGGER.info
    log("%s coverage: %s", provider, summary)


class LaunchEnricher:
    """Enrich launches while isolating provider and RPC failures."""

    def __init__(
        self,
        jupiter,
        scan_token=None,
    ) -> None:
        """Configure providers and an optional read-only scanner."""

        self.jupiter = jupiter
        self.scan_token = scan_token

    def enrich(self, report) -> SearchReport:
        """Attach analytics in discovery order."""

        envelope = report.findings.tokens
        if not isinstance(envelope, dict):
            raise ValueError(
                "Launch enrichment requires a Stonks pool envelope"
            )
        launches = envelope["pools"]
        # Multiple pools may share a mint; process each mint once.
        mints = list(dict.fromkeys(launch["mint"] for launch in launches))
        if not mints:
            LOGGER.info("No pools to enrich")
            return report

        LOGGER.info(
            "Enriching %d pools across %d unique mints",
            len(launches),
            len(mints),
        )
        LOGGER.info("Fetching Jupiter token data")
        jupiter = self.jupiter.get_tokens(mints)
        _log_coverage("Jupiter", jupiter)
        rpc = (
            OnChainEnricher(self.scan_token).scan_mints(mints)
            if self.scan_token is not None
            else {}
        )

        LOGGER.info("Joining provider snapshots with discovery records")
        # Attach snapshots in the original server order.
        for launch in launches:
            mint = launch["mint"]
            jup_data = mapping(jupiter[mint].data)
            launch["analytics"] = {
                **mapping(launch.get("analytics")),
                "jupiter": asdict(jupiter[mint]),
                "metrics": combine_metrics(
                    stonks_snapshot(launch),
                    jupiter_snapshot(jup_data),
                ),
                "on_chain": asdict(rpc[mint]) if mint in rpc else None,
            }
            candidates = stonks_links(launch)
            if jupiter[mint].status == "success":
                candidates.extend(jupiter_links(jup_data))
            enriched = attach_social(
                launch,
                candidates,
                {"stonks": "success", "jupiter": jupiter[mint].status},
            )
            launch["analytics"] = enriched["analytics"]
        return report
