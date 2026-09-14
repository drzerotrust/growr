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
        self._heading("growr | %s Scan" % self.title)
        self._line("Address", report.address)
        self._line("RPC", report.rpc)
        self._line("Timestamp", report.timestamp)
        print()
        self._render_summary(report.summary)
        if report.social is not None:
            self._render_social(report.social)
        self._render_findings(report)
        self._render_providers(report)

    def _render_summary(self, summary) -> None:
        """Print a compact summary of the scan."""

        self._heading("Summary")
        for key, value in summary.items():
            if isinstance(value, dict):
                print("  %s" % self._label(key))
                for child_key, child_value in value.items():
                    if isinstance(child_value, (list, dict)):
                        continue
                    self._line(child_key, child_value, indent=4)
            elif isinstance(value, list):
                continue
            else:
                self._line(key, value, indent=2)
        print()

    def _render_social(self, social) -> None:
        """Display reported links and explain their limits."""

        self._heading("Social presence")
        self._line("Score", "%s/100" % social["score"])
        self._table(
            ["Kind", "Link", "Sources"],
            [
                [link["kind"], link["url"], ", ".join(link["sources"])]
                for link in social["links"]
            ],
        )
        print(
            "Provider-reported presence; "
            "authenticity and activity are not verified."
        )

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
            print("  [%s] %s" % (severity, terminal_text(finding.label)))
            detail = terminal_text(finding.detail)
            source = terminal_text(finding.source)
            print("    %s (%s)" % (detail, source))
        print()

    def _render_providers(self, report) -> None:
        """Display coverage gaps alongside successful retrievals."""

        self._heading("Provider Coverage")
        for provider in report.providers:
            color = "green" if provider.status == "success" else "yellow"
            status = self._color(provider.status.upper(), color)
            name = terminal_text(provider.provider)
            if provider.operation != "token_context":
                name = "%s (%s)" % (name, terminal_text(provider.operation))
            detail = terminal_text(provider.detail)
            print("  %s: %s - %s" % (name, status, detail))


class TokenConsoleRenderer(ScanConsoleRenderer):
    """Render token mint scan reports."""

    title = "Token"

    def _render_summary(self, summary) -> None:
        """Show bounded Stonkfun tables alongside RPC facts."""

        # Reward amounts have units and interval semantics that deserve
        # dedicated sections instead of duplicate generic summary rows.
        super()._render_summary(
            {
                name: value
                for name, value in summary.items()
                if name not in {"stonks_rewards", "reward_comparison"}
            }
        )
        if "jupiter" in summary:
            self._render_jupiter(summary["jupiter"])
        if "stonks_holders" in summary:
            holders = summary["stonks_holders"].get("holders", [])
            self._heading("Stonks reported holders (first 10 returned)")
            self._table(
                ["Rank", "Address", "Tokens", "Supply %"],
                [
                    [
                        holder.get("rank"),
                        holder.get("address"),
                        holder.get("amount_tokens"),
                        holder.get("supply_percent"),
                    ]
                    for holder in holders[:10]
                ],
            )
        if "stonks_burns" in summary:
            self._render_burns(summary["stonks_burns"])
        if "stonks_rewards" in summary:
            self._render_rewards(summary["stonks_rewards"])
        if "reward_comparison" in summary:
            self._render_reward_comparison(summary["reward_comparison"])

    def _render_rewards(self, rewards) -> None:
        """Show cumulative coin payouts in their reward currency."""

        self._heading("Stonks rewards (coin-wide totals)")
        for label, name in (
            ("Reward currency", "reward_symbol"),
            ("Reward mint", "reward_mint"),
            ("Lifetime distributed tokens", "distributed_tokens"),
            ("Reported undistributed tokens", "undistributed_tokens"),
            ("Reported payout count", "payout_count"),
            ("Reported holder count", "holder_count"),
            ("Last payout", "last_payout_at"),
            ("Provider snapshot", "provider_generated_at"),
        ):
            self._line(label, rewards.get(name))

    def _render_reward_comparison(self, comparison) -> None:
        """Show observed distributions and a normalized daily rate."""

        self._heading("Reward comparison (observed interval)")
        for label, name in (
            ("Reward currency", "reward_symbol"),
            ("From", "previous_generated_at"),
            ("To", "current_generated_at"),
            ("Elapsed seconds", "elapsed_seconds"),
            ("Tokens distributed during interval", "distributed_delta_tokens"),
            ("Normalized tokens per 24 hours", "normalized_daily_tokens"),
        ):
            self._line(label, comparison.get(name))
        print(
            "The daily rate normalizes this interval; it is not a "
            "calendar-day payout, forecast or per-wallet receipt."
        )

    def _render_jupiter(self, summary) -> None:
        """Expose Jupiter audit and activity observations."""

        self._heading("Jupiter reported audit")
        for name, value in summary.get("audit", {}).items():
            self._line(name, value)
        self._heading("Jupiter trading activity")
        self._table(
            ["Interval", "Price change %", "Buy $", "Sell $", "Buys", "Sells"],
            [
                [
                    interval,
                    stats.get("priceChange"),
                    stats.get("buyVolume"),
                    stats.get("sellVolume"),
                    stats.get("numBuys"),
                    stats.get("numSells"),
                ]
                for interval, stats in summary.get("activity", {}).items()
            ],
        )

    def _render_burns(self, burns) -> None:
        """Show reported burn totals without recomputing their sum."""

        self._heading("Stonks burns (USD valued at burn time)")
        self._table(
            ["Group", "Tokens", "Historical USD", "Burn count", "Last burn"],
            [
                [
                    self._label(group),
                    totals.get("amount_tokens"),
                    totals.get("value_usd_at_burn"),
                    totals.get("burn_count"),
                    totals.get("last_burn_at"),
                ]
                for group, totals in burns.items()
                if isinstance(totals, dict)
            ],
        )


class WalletConsoleRenderer(ScanConsoleRenderer):
    """Render wallet scan reports."""

    title = "Wallet"

    def _render_summary(self, summary) -> None:
        """Show inventory addresses ready for a token-account scan."""

        super()._render_summary(summary)
        inventory = summary.get("token_accounts", {})
        if "entries" not in inventory:
            return
        self._heading("Token accounts (validated holdings)")
        self._table(
            ["Account address", "Mint", "Program", "Raw amount", "State"],
            [
                [
                    entry["address"],
                    entry["mint"],
                    entry["token_program"],
                    entry["raw_amount"],
                    entry["state"],
                ]
                for entry in inventory["entries"]
            ],
        )
        print("Inspect an entry: python3 growr.py token-account <ADDRESS>")
        print()


class TokenAccountConsoleRenderer(ScanConsoleRenderer):
    """Render SPL token-account scan reports."""

    title = "Token Account"
