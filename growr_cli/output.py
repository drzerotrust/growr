"""Select the console renderer for a completed scan or search report."""

from growr_cli.models import ScanReport
from growr_cli.renderers.base import BaseConsoleRenderer
from growr_cli.renderers.history import (
    HistoryConsoleRenderer,
    TransactionConsoleRenderer,
)
from growr_cli.renderers.jupiter import JupiterConsoleRenderer
from growr_cli.renderers.scans import (
    TokenAccountConsoleRenderer,
    TokenConsoleRenderer,
    WalletConsoleRenderer,
)
from growr_cli.renderers.stonkfun import StonkfunConsoleRenderer

_SCAN_RENDERERS = {
    "token": TokenConsoleRenderer,
    "wallet": WalletConsoleRenderer,
    "token_account": TokenAccountConsoleRenderer,
    "history": HistoryConsoleRenderer,
    "transaction": TransactionConsoleRenderer,
}
_LIST_RENDERERS = {
    "stonk": StonkfunConsoleRenderer,
    "jupiter": JupiterConsoleRenderer,
}


def renderer_for(report, use_color) -> BaseConsoleRenderer:
    """Select a specialized renderer by scan type or search provider."""

    renderer_type = (
        _SCAN_RENDERERS.get(report.scan_type)
        if isinstance(report, ScanReport)
        else _LIST_RENDERERS.get(report.findings.source)
    )
    if renderer_type is None:
        raise ValueError(
            "No console renderer is registered for this report type"
        )
    return renderer_type(use_color=use_color)
