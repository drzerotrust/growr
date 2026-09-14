"""Optional Stonkfun context for the standard RPC token scanner."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from growr_cli.analysis.rewards import compare_rewards
from growr_cli.integrations.stonks_rewards import rewards_summary
from growr_cli.integrations.stonks_token import (
    burns_summary,
    holders_summary,
    market_summary,
)
from growr_cli.logger import get_logger
from growr_cli.models import ProviderStatus

LOGGER = get_logger(__name__)


class StonksTokenContext:
    """Fetch Stonkfun snapshots without changing RPC facts."""

    def __init__(self, stonks, previous_snapshot=None) -> None:
        """Borrow the injected Stonkfun integration."""

        self.stonks = stonks
        self.previous_snapshot = previous_snapshot

    def enrich(
        self, report, mint, include_jupiter=False, include_rugcheck=False
    ) -> None:
        """Implement the token context interface using Stonkfun only.

        The standard context's provider switches do not enable other
        services in this mode. Each endpoint has its own outcome.
        """

        operations = (
            ("market", self.stonks.get_market, market_summary),
            ("holders", self.stonks.get_holders, holders_summary),
            ("burns", self.stonks.get_burns, burns_summary),
            ("rewards", self.stonks.get_rewards, rewards_summary),
        )
        LOGGER.info("Fetching Stonks market, holders, burns and rewards")
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = [
                (name, pool.submit(fetch, mint), summarize)
                for name, fetch, summarize in operations
            ]
            results = [
                (name, future.result(), summarize)
                for name, future, summarize in pending
            ]

        for name, result, summarize in results:
            key = "stonks_%s" % name
            report.provider_data[key] = asdict(result)
            report.providers.append(
                ProviderStatus("Stonks", result.status, result.detail, name)
            )
            if result.status in {"success", "partial"}:
                report.summary[key] = summarize(result.data, mint)
        statuses = ", ".join(
            "%s=%s" % (name, result.status) for name, result, _ in results
        )
        LOGGER.info("Stonks coverage: %s", statuses)
        if self.previous_snapshot is not None:
            self._compare_rewards(report)

    def _compare_rewards(self, report) -> None:
        """Keep unavailable comparisons separate from current totals."""

        LOGGER.info("Comparing Stonks reward snapshots")
        try:
            current = report.summary.get("stonks_rewards")
            comparison = compare_rewards(self.previous_snapshot, current)
        except ValueError as error:
            report.providers.append(
                ProviderStatus(
                    "Growr", "failed", str(error), "reward_comparison"
                )
            )
            LOGGER.info("Reward comparison unavailable: %s", error)
            return
        report.summary["reward_comparison"] = comparison
        report.providers.append(
            ProviderStatus(
                "Growr",
                "success",
                "Observed interval and normalized daily rate",
                "reward_comparison",
            )
        )
