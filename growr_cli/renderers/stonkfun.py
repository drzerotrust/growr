"""Market, risk, and RPC tables for Stonkfun search listings."""

from __future__ import annotations

from growr_cli.analysis.metrics import mapping, number
from growr_cli.renderers.base import terminal_text
from growr_cli.renderers.listings import ListConsoleRenderer


class StonkfunConsoleRenderer(ListConsoleRenderer):
    """Render recent, market-cap, and volume Stonkfun listings."""

    def _render_listing(self, report) -> None:
        """Build and render each listing table."""

        launches = mapping(report.findings.tokens).get("pools", [])
        platform = report.search_type != "stonk-recent"
        start = self._listing_heading(report)
        if not launches:
            print(
                "No pools on this page." if platform else "No recent launches."
            )
            return

        market_rows = []
        risk_rows = []
        rpc_rows = []
        coverage = []
        social_rows = []

        # Keep provider rankings and row identifiers aligned across
        # tables.
        for index, launch in enumerate(launches, start):
            mint = str(launch["mint"])
            symbol = terminal_text(launch.get("symbol", "?"))[:12]
            label = f"{index}. {symbol} {mint[:4]}…{mint[-4:]}"
            analytics = launch["analytics"]

            market_rows.append(
                self._market_row(label, launch, platform, report.search_type)
            )
            risk_rows.append(
                self._risk_row(label, analytics["metrics"]["risk"])
            )
            if analytics["on_chain"] is not None:
                rpc_rows.append(self._rpc_row(label, analytics["on_chain"]))
            coverage.append(self._coverage_line(label, analytics))
            social_rows.extend(self._social_rows([label], launch))

        self._render_tables(report, market_rows, risk_rows, rpc_rows, coverage)
        self._heading("Social presence")
        self._table(
            ["Token", "Social", "Website", "Social links"], social_rows
        )
        self._social_note()

    def _listing_heading(self, report) -> int:
        """Derive row numbers from the returned pagination."""

        envelope = mapping(report.findings.tokens)
        launches = envelope.get("pools", [])
        platform = report.search_type != "stonk-recent"
        mode = {
            "stonk-recent": "recent launches",
            "stonk-marketCap": "market cap",
            "stonk-volume": "volume",
        }[report.search_type]
        heading = f"Stonks {mode} | {len(launches)} results"
        start = 1
        pagination = mapping(envelope.get("pagination"))
        if platform and pagination:
            heading += " | " + ", ".join(
                f"{label}: {terminal_text(pagination.get(key, '—'))}"
                for key, label in (
                    ("page", "page"),
                    ("totalPages", "pages"),
                    ("pageSize", "page size"),
                    ("total", "total"),
                )
            )
            page, size = pagination.get("page"), pagination.get("pageSize")
            if (
                type(page) is int
                and page > 0
                and type(size) is int
                and size > 0
            ):
                start = (page - 1) * size + 1
        self._heading(heading)
        return start

    def _market_row(
        self,
        label,
        launch,
        platform,
        search_type,
    ) -> list[str]:
        """Select market values while retaining discovery order."""

        analytics = launch["analytics"]
        metrics = analytics["metrics"]
        market = metrics["market"]
        activity = metrics["activity"]["5m"]
        jup_activity = activity["jupiter"]
        change = jup_activity.get("priceChange")
        if number(mapping(change).get("value")) is None:
            change = activity["dexscreener"].get("priceChange")
        liquidity = market["token_liquidity_usd"]
        if liquidity["value"] is None:
            liquidity = market["pool_liquidity_usd"]
        row = [
            label,
            self._metric_cell(market.get("price_usd"), price=True),
            self._metric_cell(market.get("market_cap_usd")),
            self._metric_cell(liquidity),
            self._metric_cell(change, suffix="%"),
            self._metric_cell(jup_activity.get("buyVolume")),
            self._metric_cell(jup_activity.get("sellVolume")),
        ]
        if platform:
            rank_key = (
                "marketCapUsd"
                if search_type == "stonk-marketCap"
                else "volume24hUsd"
            )
            row.insert(
                1,
                self._metric_cell(
                    {"value": launch.get(rank_key), "source": "stonks"}
                ),
            )
        return row

    def _risk_row(self, label, risk) -> list[str]:
        """Format audits and convert tax basis points to percent."""

        audit = risk["audit"]
        tax = risk["transfer_tax_bps"]
        tax_percent = {
            **tax,
            "value": tax["value"] / 100 if tax["value"] is not None else None,
        }
        return [
            label,
            self._metric_cell(risk["holderCount"]),
            self._metric_cell(audit.get("topHoldersPercentage"), suffix="%"),
            self._authority_cell(audit.get("mintAuthorityDisabled")),
            self._authority_cell(audit.get("freezeAuthorityDisabled")),
            self._metric_cell(risk["organicScore"]),
            self._metric_cell(tax_percent, suffix="%"),
        ]

    def _coverage_line(self, label, analytics) -> str:
        """Explain coverage gaps for each retained launch."""

        results = {
            "jupiter": analytics["jupiter"],
            "dexscreener": analytics["dexscreener"],
        }
        if analytics["on_chain"] is not None:
            results["rpc"] = analytics["on_chain"]

        statuses = []
        for provider, result in results.items():
            status = f"{provider}={result['status']}"
            if result["status"] in {"failed", "not_configured"}:
                status += f" ({terminal_text(result['detail'])})"
            statuses.append(status)

        return f"  {label}: {', '.join(statuses)}"

    def _render_tables(
        self,
        report,
        market_rows,
        risk_rows,
        rpc_rows,
        coverage,
    ) -> None:
        """Render tables followed by source and coverage details."""

        headers = [
            "Token",
            "Price $",
            "Mcap $",
            "Liquidity $",
            "5m Δ",
            "5m buy $",
            "5m sell $",
        ]
        if report.search_type != "stonk-recent":
            headers.insert(
                1,
                "Stonks Mcap $"
                if report.search_type == "stonk-marketCap"
                else "Stonks 24h vol $",
            )
        self._table(headers, market_rows)
        self._heading("Provider-reported risk")
        self._table(
            [
                "Token",
                "Holders",
                "Top holders",
                "Mint auth",
                "Freeze auth",
                "Organic",
                "Tax",
            ],
            risk_rows,
        )
        if rpc_rows:
            self._heading("On-chain observations")
            self._table(
                ["Token", "Mint auth", "Freeze auth", "Largest accounts"],
                rpc_rows,
            )
            print(
                "Largest accounts may include pools, lockers and burn "
                "accounts. Token-2022 extensions are not decoded."
            )
        print(
            "Sources: J=Jupiter, D=Dexscreener, S=Stonks, R=RPC. D "
            "liquidity is for the selected pool."
        )
        print(
            "— = unknown. Provider audit fields and reported taxes are not "
            "independently verified."
        )
        self._heading("Coverage")
        print("\n".join(coverage))

    def _authority_cell(self, item) -> str:
        value = mapping(item).get("value")
        if not isinstance(value, bool):
            return "—"
        return "disabled J" if value else "enabled J"
