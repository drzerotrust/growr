"""Console presentation for transaction and address-history evidence."""

from growr_cli.renderers.scans import ScanConsoleRenderer


class TransactionConsoleRenderer(ScanConsoleRenderer):
    """Show outcome and source-linked actions for one signature."""

    def _render_text(self, report) -> None:
        self._heading("Transaction")
        self._line("Signature", report.address)
        evidence = report.summary["transaction"]
        if evidence is None:
            self._line("Body", "Unavailable; inspect coverage or JSON")
            return
        self._line("Execution", evidence["execution_status"])
        self._line("Slot", evidence["slot"])
        self._line("Fee (lamports)", evidence["fee_lamports"])
        self._line("Fee payer", evidence["fee_payer"])
        self._table(
            ["Action", "From", "To", "Raw amount", "Outer", "Inner"],
            [
                [
                    row[key]
                    for key in (
                        "type",
                        "from",
                        "to",
                        "raw_amount",
                        "outer_index",
                        "inner_index",
                    )
                ]
                for row in evidence["events"]
            ],
        )
        print("JSON includes balances, instructions, logs and recording gaps.")


class HistoryConsoleRenderer(ScanConsoleRenderer):
    """Show bounded address references and body coverage."""

    def _render_text(self, report) -> None:
        self._heading("Address history")
        self._line("Address", report.address)
        self._table(
            ["Signature", "Slot", "Execution", "Body"],
            [
                [
                    row[key]
                    for key in (
                        "signature",
                        "slot",
                        "execution_status",
                        "detail_status",
                    )
                ]
                for row in report.summary["entries"]
            ],
        )
        self._line(
            "Next --before", report.summary["pagination"]["next_before"]
        )
        self._line("Scope", report.summary["note"])
