"""Optional provider context for one direct token scan."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from growr_cli.analysis.metrics import mapping
from growr_cli.analysis.social import social_presence
from growr_cli.integrations.jupiter import social_links, token_summary
from growr_cli.integrations.rugcheck import report_summary
from growr_cli.logger import get_logger
from growr_cli.models import ProviderStatus

LOGGER = get_logger(__name__)


def add_coverage(report, provider, status, detail) -> None:
    """Append coverage without coupling to a scanner base class."""

    report.providers.append(ProviderStatus(provider, status, detail))


class TokenContext:
    """Compose independent providers for a direct token scan."""

    def __init__(
        self,
        jupiter,
        rugcheck,
    ) -> None:
        """Store the explicitly injected integrations."""

        self.jupiter = jupiter
        self.rugcheck = rugcheck

    def enrich(
        self,
        report,
        mint,
        include_jupiter,
        include_rugcheck,
    ) -> None:
        """Attach optional provider context."""

        LOGGER.info("Fetching market context from enabled providers")
        # Fetch independent sources together, then report each outcome.
        with ThreadPoolExecutor(max_workers=2) as pool:
            rugcheck_future = (
                pool.submit(self.rugcheck.get_report, mint)
                if include_rugcheck
                else None
            )
            jupiter_future = (
                pool.submit(self.jupiter.get_token, mint)
                if include_jupiter
                else None
            )
            rugcheck_result = (
                rugcheck_future.result()
                if rugcheck_future is not None
                else None
            )
            jupiter_result = (
                jupiter_future.result() if jupiter_future is not None else None
            )

        retain_provider_data(report, rugcheck_result, jupiter_result)

        if rugcheck_result is not None:
            rugcheck = mapping(rugcheck_result.data)
            rugcheck_error = (
                rugcheck_result.detail
                if rugcheck_result.status == "failed"
                else None
            )
            if rugcheck_error:
                add_coverage(report, "Rugcheck", "failed", rugcheck_error)
            elif rugcheck:
                report.summary["rugcheck"] = report_summary(rugcheck)
                add_coverage(
                    report, "Rugcheck", "success", "Token report found"
                )
            else:
                add_coverage(
                    report, "Rugcheck", "no_data", "No report returned"
                )

        if jupiter_result is not None:
            jupiter = mapping(jupiter_result.data)
            report.social = social_presence(
                social_links(jupiter), {"jupiter": jupiter_result.status}
            )
            jupiter_error = (
                jupiter_result.detail
                if jupiter_result.status in {"failed", "not_configured"}
                else None
            )
            if jupiter_error == "Jupiter API key is not configured":
                add_coverage(
                    report, "Jupiter", "not_configured", jupiter_error
                )
            elif jupiter_error:
                add_coverage(report, "Jupiter", "failed", jupiter_error)
            elif jupiter:
                report.summary["jupiter"] = token_summary(jupiter)
                add_coverage(
                    report, "Jupiter", "success", "Token enrichment found"
                )
            else:
                add_coverage(
                    report, "Jupiter", "no_data", "No token record returned"
                )


def retain_provider_data(report, rugcheck, jupiter) -> None:
    """Retain fetched HTTP outcomes for optional machine raw output."""

    for source, result in (
        ("rugcheck", rugcheck),
        ("jupiter", jupiter),
    ):
        if result is not None:
            report.provider_data[source] = asdict(result)
