"""Shared listing presentation and evidence formatting."""

from __future__ import annotations

from abc import abstractmethod
from itertools import zip_longest

from growr_cli.analysis.metrics import mapping, number
from growr_cli.models import SearchReport
from growr_cli.renderers.base import BaseConsoleRenderer, terminal_text


class ListConsoleRenderer(BaseConsoleRenderer):
    """Shared validation and metric formatting for listings."""

    def _render_text(self, report) -> None:
        if not isinstance(report, SearchReport):
            raise TypeError("List renderers require a SearchReport")
        self._render_listing(report)

    @abstractmethod
    def _render_listing(self, report) -> None:
        """Render a provider-specific listing."""

    def _metric_cell(self, item, *, price=False, suffix="") -> str:
        data = mapping(item)
        value = number(data.get("value"))
        if value is None:
            return "—"
        # Percent placeholders do not support comma grouping.
        formatted = (
            "%.6g" % value
            if price
            else format(value, ",.2f").rstrip("0").rstrip(".")
        )
        source = {
            "jupiter": "J",
            "stonks": "S",
            "rpc": "R",
        }.get(str(data.get("source")), "?")
        return "%s%s %s" % (formatted, suffix, source)

    def _social_rows(self, identity, record) -> list[list[str]]:
        """Show every link, with continuation rows and source labels."""

        social = mapping(mapping(record.get("analytics")).get("social"))
        websites = []
        socials = []
        for link in social.get("links", []):
            sources = ", ".join(link["sources"])
            text = terminal_text("%s [%s]" % (link["url"], sources))
            if link["kind"] == "website":
                websites.append(text)
            else:
                socials.append(text)
        score = social.get("score")
        score_text = "%s/100" % score if score is not None else "—"
        rows = []
        for index, (website, account) in enumerate(
            zip_longest(websites or ["—"], socials or ["—"], fillvalue="")
        ):
            prefix = identity if index == 0 else [""] * len(identity)
            rows.append(
                [
                    *[terminal_text(value) for value in prefix],
                    score_text if index == 0 else "",
                    website,
                    account,
                ]
            )
        return rows

    def _social_note(self) -> None:
        """Explain observed presence and incomplete retrieval."""

        print(
            "Social presence: website +40, first platform +40, second +20. "
            "Links are provider-reported; authenticity and activity are "
            "not verified. Zero means no valid links observed."
        )

    def _rpc_row(self, label, result) -> list[str]:
        """Format RPC authorities and account concentration."""

        summary = mapping(mapping(result.get("data")).get("summary"))
        mint_data = mapping(summary.get("mint"))
        holders = mapping(summary.get("holders"))
        concentration = {
            "value": holders.get("top_twenty_percent"),
            "source": "rpc",
        }

        return [
            label,
            self._rpc_authority(mint_data, "mint_authority"),
            self._rpc_authority(mint_data, "freeze_authority"),
            self._metric_cell(concentration, suffix="%"),
        ]

    def _rpc_authority(self, data, key) -> str:
        if key not in data:
            return "—"
        return "enabled R" if data[key] else "disabled R"
