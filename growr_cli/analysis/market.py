"""Market precedence and activity over normalized token snapshots."""

from typing import Any

from growr_cli.analysis.metrics import metric, number


def combine_activity(jupiter) -> dict[str, Any]:
    """Derive volume ratios from the same source and interval."""

    activity = {}
    for interval in ("5m", "1h", "6h", "24h"):
        stats = jupiter.activity[interval]
        values = dict(stats.values)
        buy = stats.buy_volume
        sell = stats.sell_volume
        if buy is not None and sell is not None and buy >= 0 and sell >= 0:
            total = buy + sell
            values["net_buy_volume_usd"] = metric(buy - sell, jupiter.source)
            values["buy_volume_share"] = metric(
                buy / total if total > 0 else None, jupiter.source
            )
        activity[interval] = {
            "jupiter": values,
        }
    return activity


def combine_metrics(
    launch,
    jupiter,
) -> dict[str, Any]:
    """Apply source precedence and preserve measurement scope."""

    market = {}
    for name in ("price_usd", "market_cap_usd", "fdv_usd"):
        for snapshot in (jupiter, launch):
            value = snapshot.market.get(name)
            if number(value) is not None:
                market[name] = metric(value, snapshot.source)
                break
    market["token_liquidity_usd"] = jupiter.market["token_liquidity_usd"]
    market["stonks_volume_24h_usd"] = launch.market["stonks_volume_24h_usd"]
    return {
        "market": market,
        "risk": {**jupiter.risk, **launch.risk},
        "activity": combine_activity(jupiter),
    }
