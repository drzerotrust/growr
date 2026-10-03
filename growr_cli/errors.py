"""Handle stable human and machine-readable CLI errors."""

import sys

from growr_cli.logger import get_logger
from growr_cli.machine.response import build_response, serialize
from growr_cli.safety import safe_text

LOGGER = get_logger(__name__)


class JsonArgumentError(ValueError):
    """Signal invalid CLI arguments without echoing their values."""


def _emit_failure(run, args, code, message) -> None:
    """Write one complete error document with a stable public code."""

    response = build_response(
        run, args, error={"code": code, "message": message}
    )
    print(serialize(response))


def _log_error(args, message, logger=None) -> None:
    """Keep human failures visible and default JSON free of logs."""

    message = safe_text(message)
    logger = logger or LOGGER
    logger.error("%s", message)
    if not (args.json or args.verbose or args.quiet):
        print("growr: %s" % message, file=sys.stderr)
