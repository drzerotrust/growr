"""Jupiter discovery market, social and RPC tables."""

from growr_cli.analysis.metrics import mapping
from growr_cli.renderers.base import terminal_text
from growr_cli.renderers.listings import ListConsoleRenderer


class JupiterConsoleRenderer(ListConsoleRenderer):
    """Render discovery identity and social presence as a table."""

    def _render_listing(self, report) -> None:
        tokens = report.findings.tokens
        self._heading(
            "Jupiter %s | %s results" % (report.search_type, len(tokens))
        )
        self._render_market(tokens)
        rows = []
        for token in tokens:
            rows.extend(
                self._social_rows(
                    [
                        token.get("symbol", "—"),
                        token.get("id", "—"),
                    ],
                    token,
                )
            )
        self._table(
            ["Symbol", "Mint", "Social", "Website", "Social links"], rows
        )
        self._social_note()
        self._render_rpc(tokens)

    def _render_rpc(self, tokens) -> None:
        """Show optional observations and coverage gaps."""

        rows = []
        for token in tokens:
            result = mapping(token.get("analytics")).get("on_chain")
            if result is None:
                continue
            label = terminal_text(token.get("id") or "—")
            rows.append(
                [
                    *self._rpc_row(label, result),
                    terminal_text(result["status"]),
                    terminal_text(result.get("detail") or ""),
                ]
            )
        if rows:
            self._heading("On-chain observations")
            self._table(
                [
                    "Token",
                    "Mint auth",
                    "Freeze auth",
                    "Largest accounts",
                    "Status",
                    "Detail",
                ],
                rows,
            )

    def _render_market(self, tokens) -> None:
        """Show token-level Jupiter measurements."""

        rows = []
        for token in tokens:
            analytics = mapping(token.get("analytics"))
            metrics = mapping(analytics.get("metrics"))
            values = mapping(metrics.get("jupiter")).get("values", {})
            rows.append(
                [
                    token.get("name", "—"),
                    token.get("symbol", "—"),
                    token.get("id", "—"),
                    values.get("price_usd"),
                    values.get("market_cap"),
                    values.get("liquidity"),
                    values.get("holder_count"),
                    values.get("organic_score"),
                ]
            )
        self._table(
            [
                "Name",
                "Symbol",
                "Mint",
                "Price $",
                "Mcap $",
                "Token liquidity $",
                "Holders",
                "Organic",
            ],
            rows,
        )
        print(
            "Source: Jupiter. — = unknown; "
            "provider indicators are not RPC facts."
        )
