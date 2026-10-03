"""Pure number validation and sourced measurement helpers."""

import math
from typing import Any


def number(value) -> float | None:
    """Accept finite numbers and decimal strings, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result):
        return None

    return result


def mapping(value) -> dict[str, Any]:
    """Accept provider objects only when they are dictionaries."""

    if isinstance(value, dict):
        return value

    return {}


def metric(value, source, scope="token") -> dict[str, Any]:
    """Attach provenance and scope while preserving missing values."""

    return {"value": value, "source": source, "scope": scope}
