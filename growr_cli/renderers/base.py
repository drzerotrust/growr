"""Terminal and JSON renderers for CLI scan reports."""

from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod

from growr_cli.safety import safe_text

_TERMINAL_ESCAPE = re.compile(
    r"\x1b\].*?(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]", re.DOTALL
)


def terminal_text(value) -> str:
    """Remove terminal controls and nonprinting characters."""

    text = _TERMINAL_ESCAPE.sub("", safe_text(value))
    return "".join(character for character in text if character.isprintable())


class BaseConsoleRenderer(ABC):
    """Shared JSON output and terminal formatting primitives."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
    }

    def __init__(self, use_color) -> None:
        """Create a renderer.

        Args:
            use_color: Request ANSI colors. Ignored when stdout is not a
                TTY.
        """

        self.use_color = use_color and sys.stdout.isatty()

    def render(self, report) -> None:
        """Render the human-readable view of a completed report."""

        self._render_text(report)

    @abstractmethod
    def _render_text(self, report) -> None:
        """Render the human-readable view for this report type."""

    def _table(self, headers, rows) -> None:
        headers = [terminal_text(cell) for cell in headers]
        rows = [[terminal_text(cell) for cell in row] for row in rows]
        widths = [
            max(len(row[i]) for row in [headers, *rows])
            for i in range(len(headers))
        ]
        for row in [headers, *rows]:
            print(
                "  ".join(
                    cell.ljust(width)
                    for cell, width in zip(row, widths, strict=True)
                ).rstrip()
            )
        print()

    def _heading(self, text) -> None:
        print(self._color(text, "bold"))

    def _line(self, label, value, indent=2) -> None:
        print(f"{' ' * indent}{self._label(label)}: {terminal_text(value)}")

    def _label(self, label) -> str:
        return terminal_text(label).replace("_", " ").title()

    def _severity_color(self, severity) -> str:
        if severity in {"critical", "high"}:
            return "red"
        if severity == "medium":
            return "yellow"
        return "green"

    def _color(self, text, color) -> str:
        text = terminal_text(text)
        if not self.use_color:
            return text
        return f"{self.COLORS[color]}{text}{self.COLORS['reset']}"
