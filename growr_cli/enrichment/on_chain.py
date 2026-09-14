"""Shared optional Solana verification for discovery listings."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone

from solders.pubkey import Pubkey

from growr_cli.analysis.metrics import mapping
from growr_cli.logger import get_logger, suppress_console_logs
from growr_cli.models import EnrichmentResult, SearchReport

LOGGER = get_logger(__name__)


class OnChainEnricher:
    """Deduplicate RPC work and retain verification coverage."""

    def __init__(self, scan_token) -> None:
        """Borrow a callback that owns each scan's RPC connection."""

        self.scan_token = scan_token

    def scan_mints(self, mints) -> dict[str, EnrichmentResult]:
        """Scan unique mints with two workers and summarize coverage."""

        mints = list(dict.fromkeys(mints))
        if not mints:
            return {}
        LOGGER.info(
            "Verifying %d mints on-chain with up to 2 workers", len(mints)
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = dict(
                zip(mints, pool.map(self._scan, mints), strict=True)
            )
        counts = Counter(result.status for result in results.values())
        summary = ", ".join(
            "%s=%s" % (status, count)
            for status, count in sorted(counts.items())
        )
        log = LOGGER.warning if counts["failed"] else LOGGER.info
        log("RPC coverage: %s", summary)
        return results

    def enrich(self, report) -> SearchReport:
        """Attach verification to Jupiter token discovery."""

        tokens = report.findings.tokens
        mints = [
            token["id"] for token in tokens if isinstance(token.get("id"), str)
        ]
        results = self.scan_mints(mints)
        for token in tokens:
            result = self._result(token, results)
            token["analytics"] = {
                **mapping(token.get("analytics")),
                "on_chain": asdict(result),
            }
        LOGGER.info(
            "RPC verification retained %d discovery results", len(tokens)
        )
        return report

    def _result(self, token, results) -> EnrichmentResult:
        """Explain absent mint identities before RPC lookup."""

        mint = token.get("id")
        if not isinstance(mint, str):
            return EnrichmentResult(
                "failed", None, detail="Missing Solana mint address"
            )
        return results[mint]

    def _scan(self, mint) -> EnrichmentResult:
        try:
            # Reject malformed discovery identities before opening RPC.
            Pubkey.from_string(mint)
            # Individual scans report phases normally; this batch gets
            # one coverage summary instead of repeating logs per mint.
            with suppress_console_logs():
                report = self.scan_token(mint)
            return EnrichmentResult(
                "success",
                datetime.now(timezone.utc).isoformat(),
                report.to_dict(),
            )
        except Exception as error:
            # Arbitrary SDK exception messages may contain a
            # credential-bearing endpoint.
            return EnrichmentResult(
                "failed",
                datetime.now(timezone.utc).isoformat(),
                detail="On-chain scan failed (%s)" % type(error).__name__,
            )
