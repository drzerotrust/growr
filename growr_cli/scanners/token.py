"""TokenScanner workflow and report assembly."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from growr_cli.analysis.risk import (
    holder_finding,
    mint_findings,
    risk_band,
    score_findings,
)
from growr_cli.logger import get_logger
from growr_cli.models import ScanReport
from growr_cli.scanners.base import BaseScanner
from growr_cli.scanners.observations import optional_result
from growr_cli.solana.decoding import parse_mint
from growr_cli.solana.holders import read_holders
from growr_cli.solana.metadata import read_metadata

LOGGER = get_logger(__name__)


class TokenScanner(BaseScanner):
    """Scan mint facts, metadata, holders, and market context."""

    def __init__(self, rpc, rpc_label, context) -> None:
        """Create a token scanner.

        Args:
            rpc: Read-only Solana RPC client.
            rpc_label: Secret-free RPC label for the report.
            context: Optional market context workflow.
        """

        super().__init__(rpc, rpc_label)
        self.context = context

    def scan(
        self,
        mint_text,
        include_jupiter,
        include_rugcheck,
        *,
        include_market_context=True,
    ) -> ScanReport:
        """Scan mint facts before fetching optional provider data.

        Args:
            mint_text: Token mint address.
            include_jupiter: Whether to request Jupiter enrichment.
            include_rugcheck: Whether to request a Rugcheck report.
            include_market_context: Request provider data; False
                performs only RPC reads.

        Returns:
            A completed token scan report.

        Raises:
            ValueError: If the address is invalid, missing, or not an
                SPL mint.
        """

        mint = self.rpc.parse_address(mint_text)
        report = self.new_report("token", mint_text)

        # Validate ownership before interpreting the SPL binary layout.
        LOGGER.info("Reading and validating the mint account")
        mint_data, mint_owner = self.rpc.get_account_data(mint)
        if mint_data is None or mint_owner is None:
            raise ValueError(
                "Mint account was not found on the configured RPC"
            )
        mint_summary = parse_mint(mint_data, mint_owner)
        report.summary["mint"] = mint_summary
        self._add_mint_findings(report, mint_summary)

        # Metadata and holder reads are independent of each other.
        LOGGER.info("Reading metadata and largest token accounts")
        with ThreadPoolExecutor(max_workers=2) as pool:
            metadata_future = pool.submit(self._read_metadata, mint)
            holders_future = pool.submit(
                self._read_holders,
                mint,
                mint_summary["supply"],
                mint_summary["decimals"],
                mint_summary["program_id"],
            )
            metadata = optional_result(metadata_future, report, "metadata")
            holders = optional_result(holders_future, report, "holders")

        if metadata is not None:
            report.summary["metadata"] = metadata
        if holders is not None:
            report.summary["holders"] = holders
            report.findings.append(holder_finding(holders))

        if include_market_context:
            self.context.enrich(
                report, mint_text, include_jupiter, include_rugcheck
            )
        LOGGER.info("Scoring token findings")
        report.summary["risk_score"] = self._score_findings(report.findings)
        report.summary["risk_band"] = self._risk_band(
            report.summary["risk_score"]
        )
        return report

    def _add_mint_findings(self, report, mint) -> None:
        report.findings.extend(mint_findings(mint))

    _score_findings = staticmethod(score_findings)
    _risk_band = staticmethod(risk_band)

    def _read_metadata(self, mint) -> dict[str, Any]:
        return read_metadata(self.rpc, mint)

    def _read_holders(
        self, mint, supply_text, decimals, program=None
    ) -> dict[str, Any]:
        return read_holders(self.rpc, mint, supply_text, decimals, program)
