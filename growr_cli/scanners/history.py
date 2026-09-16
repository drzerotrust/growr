"""Bounded address history and individual transaction evidence."""

from typing import Any

from growr_cli.analysis.transactions import normalize_transaction
from growr_cli.logger import get_logger
from growr_cli.models import CoverageStatus, ProviderStatus, ScanReport
from growr_cli.scanners.base import BaseScanner
from growr_cli.solana.rpc import RpcError
from growr_cli.solana.signatures import signature_records

LOGGER = get_logger(__name__)


class HistoryScanner(BaseScanner):
    """Fetch one address page and optional bodies without traversal."""

    def transaction(self, signature) -> ScanReport:
        """Read one signature and retain unavailable-body coverage."""

        report = self.new_report("transaction", signature)
        LOGGER.info("Reading transaction evidence")
        evidence, status = self._transaction(signature)
        report.summary.update(
            available=evidence is not None, transaction=evidence
        )
        report.providers.append(
            ProviderStatus("rpc", status, signature, "transaction_body")
        )
        return report

    def history(
        self, address, limit=20, before=None, until=None, details=False
    ) -> ScanReport:
        """Retain a page, its continuation and detail failures."""

        report = self.new_report("history", address)
        LOGGER.info(
            "Reading address history%s",
            " and transaction bodies" if details else "",
        )
        entries = self.rpc.get_signatures(
            self.rpc.parse_address(address), limit, before=before, until=until
        )
        if len(entries) > limit:
            report.providers.append(
                ProviderStatus(
                    "rpc",
                    "partial",
                    "Provider exceeded requested page size",
                    "signatures",
                )
            )
            entries = entries[:limit]
        signatures = signature_records(entries)
        rows = []
        for entry in signatures:
            body, status = (
                self._transaction(entry["signature"])
                if details
                else (None, "skipped")
            )
            rows.append(
                {**entry, "transaction": body, "detail_status": status}
            )
            if details:
                report.providers.append(
                    ProviderStatus(
                        "rpc", status, entry["signature"], "transaction_body"
                    )
                )
        full_page = len(entries) >= limit
        report.summary.update(
            scope="address_references",
            entries=rows,
            pagination={
                "limit": limit,
                "before": before,
                "until": until,
                "next_before": str(entries[-1].signature)
                if full_page and signatures
                else None,
                "provider_page_exhausted": not full_page,
                "complete_history": False,
            },
            note="References to this address only. Closed or other token "
            "accounts may require separate history. Provider retention "
            "and this page limit do not establish lifetime completeness.",
        )
        return report

    def _transaction(
        self, signature
    ) -> tuple[dict[str, Any] | None, CoverageStatus]:
        """Isolate missing, unsupported and malformed bodies."""

        try:
            body = self.rpc.get_transaction(signature)
            if body is None:
                # A listed signature with no available body is a gap,
                # rather than evidence that no activity took place.
                return None, "partial"
            evidence = normalize_transaction(body, signature)
            return evidence, (
                "success" if all(evidence["recording"].values()) else "partial"
            )
        except (RpcError, ValueError, KeyError, TypeError, IndexError):
            return None, "failed"
