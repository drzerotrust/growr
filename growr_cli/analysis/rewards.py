"""Exact reward quantities and comparisons of provider snapshots."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Any


def raw_amount(value) -> int:
    """Require nonnegative base units represented as ASCII digits."""

    if not isinstance(value, str) or not (
        value.isascii() and value.isdecimal()
    ):
        raise ValueError("Reward base units must be decimal strings")
    return int(value)


def token_amount(value, decimals) -> str:
    """Insert a decimal point without rounding integer totals."""

    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Reward decimals must be between 0 and 255")
    digits = str(raw_amount(value))
    if decimals == 0:
        return digits
    digits = digits.rjust(decimals + 1, "0")
    amount = "%s.%s" % (digits[:-decimals], digits[-decimals:])
    return amount.rstrip("0").rstrip(".")


def snapshot_time(value) -> datetime:
    """Require a timezone-aware provider timestamp and normalize UTC."""

    if not isinstance(value, str):
        raise ValueError("Reward snapshot timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        pass
    raise ValueError("Reward snapshot timestamp is invalid")


def validate_snapshot(snapshot) -> None:
    """Check the normalized fields required for reward comparisons."""

    if not isinstance(snapshot, dict) or snapshot.get("mode") != "reward":
        raise ValueError("A reward-mode snapshot is required")
    for name in ("mint", "reward_mint"):
        if not isinstance(snapshot.get(name), str) or not snapshot[name]:
            raise ValueError("Reward snapshot identifiers are unavailable")
    token_amount(snapshot.get("distributed_raw"), snapshot.get("decimals"))
    snapshot_time(snapshot.get("provider_generated_at"))


def compare_rewards(previous, current) -> dict[str, Any]:
    """Measure an interval and normalize its rate to 24 hours."""

    validate_snapshot(previous)
    validate_snapshot(current)
    if any(
        previous[name] != current[name]
        for name in ("mint", "reward_mint", "decimals")
    ):
        raise ValueError("Reward mint or decimals changed between snapshots")
    start = snapshot_time(previous["provider_generated_at"])
    end = snapshot_time(current["provider_generated_at"])
    if end <= start:
        raise ValueError("Reward snapshot time must advance for comparison")
    delta = raw_amount(current["distributed_raw"]) - raw_amount(
        previous["distributed_raw"]
    )
    if delta < 0:
        raise ValueError(
            "Cumulative rewards decreased; comparison unavailable"
        )

    # Provider timestamps avoid counting a cached response as a new
    # interval. Integer microseconds retain subsecond precision.
    elapsed = end - start
    microseconds = (
        elapsed.days * 86400 + elapsed.seconds
    ) * 1000000 + elapsed.microseconds
    with localcontext() as context:
        context.prec = 28
        daily = Decimal(delta * 86400 * 1000000) / Decimal(
            microseconds * 10 ** current["decimals"]
        )
    # Keep Decimal digits exact; percent-f converts to float.
    return {
        "mint": current["mint"],
        "reward_mint": current["reward_mint"],
        "reward_symbol": current.get("reward_symbol"),
        "decimals": current["decimals"],
        "previous_generated_at": start.isoformat(),
        "current_generated_at": end.isoformat(),
        "elapsed_seconds": microseconds / 1000000,
        "distributed_delta_raw": str(delta),
        "distributed_delta_tokens": token_amount(
            str(delta), current["decimals"]
        ),
        "normalized_daily_tokens": format(daily, "f"),
    }
