"""Optional provider context for one direct token scan."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from growr_cli.analysis.market import select_single_pair
from growr_cli.analysis.metrics import mapping
from growr_cli.integrations.dexscreener import (
    pair_summary,
    pool_snapshot,
)
from growr_cli.integrations.jupiter import token_summary
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
        dexscreener,
        rugcheck,
    ) -> None:
        """Store the explicitly injected integrations."""

        self.jupiter = jupiter
        self.dexscreener = dexscreener
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
        with ThreadPoolExecutor(max_workers=3) as pool:
            dex_future = pool.submit(self.dexscreener.get_pairs, mint)
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
            dex_result = dex_future.result()
            pairs = (
                dex_result.data if isinstance(dex_result.data, list) else []
            )
            dex_error = (
                dex_result.detail if dex_result.status == "failed" else None
            )
            rugcheck_result = (
                rugcheck_future.result()
                if rugcheck_future is not None
                else None
            )
            jupiter_result = (
                jupiter_future.result() if jupiter_future is not None else None
            )

        if dex_error:
            add_coverage(report, "Dexscreener", "failed", dex_error)
        elif pairs:
            best_pair = select_single_pair(
                [pool_snapshot(pair) for pair in pairs]
            )
            report.summary["market"] = pair_summary(best_pair.raw)
            add_coverage(report, "Dexscreener", "success", "Market pair found")
        else:
            add_coverage(
                report, "Dexscreener", "no_data", "No Solana market pair found"
            )

        retain_provider_data(
            report, dex_result, rugcheck_result, jupiter_result
        )

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


def retain_provider_data(report, dex, rugcheck, jupiter) -> None:
    """Retain fetched HTTP outcomes for optional machine raw output."""

    for source, result in (
        ("dexscreener", dex),
        ("rugcheck", rugcheck),
        ("jupiter", jupiter),
    ):
        if result is not None:
            report.provider_data[source] = asdict(result)
