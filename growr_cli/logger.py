"""Application logs with elapsed time and a dedicated stderr console."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from growr_cli.safety import safe_text

_CONSOLE_SUPPRESSED = ContextVar("console_suppressed", default=False)


class ConsoleFormatter(logging.Formatter):
    """Format one execution event with elapsed time and its severity."""

    COLORS = {
        logging.INFO: "\033[36m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
    }

    def __init__(self, use_color) -> None:
        """Start the elapsed-time clock for this run."""

        super().__init__()
        self.started_at = perf_counter()
        self.use_color = use_color

    def format(self, record) -> str:
        """Keep each event on one line, with optional severity color."""

        elapsed = perf_counter() - self.started_at
        level = record.levelname
        if self.use_color and sys.stderr.isatty():
            color = self.COLORS.get(record.levelno, "")
            level = "%s%s\033[0m" % (color, level)

        message = " ".join(safe_text(record.getMessage()).splitlines())
        message = "".join(char for char in message if char.isprintable())
        return "[+%7.2fs] %s %s" % (elapsed, level, message)


class ConsoleHandler(logging.Handler):
    """Write application events immediately to the current stderr."""

    def emit(self, record) -> None:
        """Write unsuppressed console events to stderr."""

        if _CONSOLE_SUPPRESSED.get():
            return

        # Resolve stderr here to support redirection and repeated runs.
        print(self.format(record), file=sys.stderr, flush=True)


def configure_console_logging(
    *, use_color=True, quiet=False, enabled=False
) -> None:
    """Keep console logs disabled unless explicitly enabled."""

    root = logging.getLogger("growr_cli")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    # Repeated CLI calls replace only our console, preserving file logs.
    for handler in root.handlers[:]:
        if isinstance(handler, ConsoleHandler):
            root.removeHandler(handler)
            handler.close()

    if not enabled:
        if not root.handlers:
            root.addHandler(logging.NullHandler())
        return

    handler = ConsoleHandler()
    handler.setLevel(logging.WARNING if quiet else logging.INFO)
    handler.setFormatter(ConsoleFormatter(use_color))
    root.addHandler(handler)


def get_logger(file_name) -> logging.Logger:
    """Get an application logger, silent until output is configured."""

    root = logging.getLogger("growr_cli")
    root.propagate = False
    if not root.handlers:
        root.addHandler(logging.NullHandler())

    name = (
        file_name
        if file_name.startswith("growr_cli.")
        else "growr_cli.%s" % file_name
    )
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    return logger


@contextmanager
def suppress_console_logs() -> Iterator[None]:
    """Silence a worker while its batch gets a single summary."""

    token = _CONSOLE_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _CONSOLE_SUPPRESSED.reset(token)
