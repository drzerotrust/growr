"""Pair selection and precedence over normalized snapshots."""

from typing import Any

from growr_cli.analysis.metrics import metric, number
from growr_cli.models import PoolSnapshot


def select_launch_pair(pairs, mint, original_pool) -> PoolSnapshot | None:
    """Prefer the launch pool, then a liquid exact base-mint match."""

    valid = [
        pair
        for pair in pairs
        if pair.chain == "solana" and pair.base_mint == mint
    ]
    for pair in valid:
        if pair.address and pair.address == original_pool:
            return pair
    return max(
        valid,
        key=lambda pair: (
            number(pair.liquidity) or 0,
            str(pair.address),
        ),
        default=None,
    )


def select_single_pair(pairs) -> PoolSnapshot:
    """Select numeric liquidity; preserve the first pair on ties."""

    best_pair = pairs[0]
    best_liquidity = 0.0
    for pair in pairs:
        value = (
            float(pair.liquidity)
            if isinstance(pair.liquidity, (int, float))
            else 0.0
        )
        if value > best_liquidity:
            best_pair = pair
            best_liquidity = value
    return best_pair


def combine_activity(jupiter, dexscreener) -> dict[str, Any]:
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
            "dexscreener": dexscreener.activity[interval].values,
        }
    return activity


def combine_metrics(
    launch,
    jupiter,
    dexscreener,
) -> dict[str, Any]:
    """Apply source precedence and preserve measurement scope."""

    market = {}
    for name in ("price_usd", "market_cap_usd", "fdv_usd"):
        for snapshot in (jupiter, dexscreener, launch):
            value = snapshot.market.get(name)
            if number(value) is not None:
                market[name] = metric(value, snapshot.source)
                break
    market["token_liquidity_usd"] = jupiter.market["token_liquidity_usd"]
    market["pool_liquidity_usd"] = dexscreener.market["pool_liquidity_usd"]
    market["stonks_volume_24h_usd"] = launch.market["stonks_volume_24h_usd"]
    return {
        "market": market,
        "risk": {**jupiter.risk, **launch.risk},
        "activity": combine_activity(jupiter, dexscreener),
    }
