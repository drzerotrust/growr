"""BaseScanner workflow and report assembly."""

from __future__ import annotations

from datetime import datetime, timezone

from growr_cli.analysis.risk import severity_for_percentage
from growr_cli.models import (
    ProviderStatus,
    ScanReport,
)


class BaseScanner:
    """Shared report helpers. The point is consistency, not wizardry."""

    def __init__(
        self,
        rpc,
        rpc_label,
    ) -> None:
        """Store scan dependencies.

        Args:
            rpc: Read-only Solana RPC client.
            rpc_label: Secret-free label for the RPC used by this scan.
        """

        self.rpc = rpc
        self.rpc_label = rpc_label

    def new_report(self, scan_type, address) -> ScanReport:
        """Start a report with enough provenance to debug it later.

        Args:
            scan_type: Report mode name.
            address: Address being scanned.

        Returns:
            An empty report with provenance fields filled in.
        """

        return ScanReport(
            scan_type=scan_type,
            address=address,
            rpc=self.rpc_label,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def add_provider(
        self,
        report,
        provider,
        status,
        detail,
    ) -> None:
        """Record coverage independently of optional data success.

        Args:
            report: Report to update.
            provider: Provider name.
            status: Coverage outcome.
            detail: Short explanation.
        """

        report.providers.append(ProviderStatus(provider, status, detail))

    severity_for_percentage = staticmethod(severity_for_percentage)
