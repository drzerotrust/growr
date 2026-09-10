"""Shared scan presentation and renderers for each scan type."""

from __future__ import annotations

from growr_cli.models import ScanReport
from growr_cli.renderers.base import BaseConsoleRenderer, terminal_text


class ScanConsoleRenderer(BaseConsoleRenderer):
    """Shared summary, findings, and coverage for on-chain scans."""

    title = "Scan"

    def _render_text(self, report) -> None:
        if not isinstance(report, ScanReport):
            raise TypeError("Scan renderers require a ScanReport")
        self._heading(f"growr | {self.title} Scan")
        self._line("Address", report.address)
        self._line("RPC", report.rpc)
        self._line("Timestamp", report.timestamp)
        print()
        self._render_summary(report.summary)
        self._render_findings(report)
        self._render_providers(report)

    def _render_summary(self, summary) -> None:
        """Print a compact summary of the scan."""

        self._heading("Summary")
        for key, value in summary.items():
            if isinstance(value, dict):
                print(f"  {self._label(key)}")
                for child_key, child_value in value.items():
                    if isinstance(child_value, (list, dict)):
                        continue
                    self._line(child_key, child_value, indent=4)
            elif isinstance(value, list):
                continue
            else:
                self._line(key, value, indent=2)
        print()

    def _render_findings(self, report) -> None:
        """Display findings in their original scan order."""

        self._heading("Findings")
        if not report.findings:
            print(
                "  No immediate findings. The chain remains weird, just "
                "less visibly weird."
            )
        for finding in report.findings:
            color = self._severity_color(finding.severity)
            severity = self._color(finding.severity.upper(), color)
            print(f"  [{severity}] {terminal_text(finding.label)}")
            detail = terminal_text(finding.detail)
            source = terminal_text(finding.source)
            print(f"    {detail} ({source})")
        print()

    def _render_providers(self, report) -> None:
        """Display coverage gaps alongside successful retrievals."""

        self._heading("Provider Coverage")
        for provider in report.providers:
            color = "green" if provider.status == "success" else "yellow"
            status = self._color(provider.status.upper(), color)
            name = terminal_text(provider.provider)
            detail = terminal_text(provider.detail)
            print(f"  {name}: {status} - {detail}")


class TokenConsoleRenderer(ScanConsoleRenderer):
    """Render token mint scan reports."""

    title = "Token"


class WalletConsoleRenderer(ScanConsoleRenderer):
    """Render wallet scan reports."""

    title = "Wallet"


class TokenAccountConsoleRenderer(ScanConsoleRenderer):
    """Render SPL token-account scan reports."""

    title = "Token Account"
