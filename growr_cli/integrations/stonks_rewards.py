"""Stonkfun reward totals, validation and field translation."""

from typing import Any

from solders.pubkey import Pubkey

from growr_cli.analysis.rewards import raw_amount, snapshot_time, token_amount
from growr_cli.integrations.http import provider_result
from growr_cli.integrations.stonks_api import fetch
from growr_cli.models import EnrichmentResult


def get_rewards(http, mint) -> EnrichmentResult:
    """Fetch one exact coin's reward totals."""

    envelope, error = fetch(http, "tokens/%s/rewards" % mint)
    if error:
        return provider_result("failed", envelope, error)
    data = envelope["data"]
    if data.get("mint") != mint:
        return _invalid(envelope)
    if data.get("mode") == "standard" and "rewards" in data:
        if data["rewards"] is None:
            return provider_result(
                "no_data", envelope, "Standard-mode coin has no holder rewards"
            )
        return _invalid(envelope)
    try:
        rewards_summary(envelope, mint)
    except (ValueError, TypeError, KeyError):
        return _invalid(envelope)
    return provider_result(
        "success", envelope, "Provider-reported reward totals"
    )


def _invalid(envelope) -> EnrichmentResult:
    return provider_result(
        "failed", envelope, "Stonks returned an unexpected rewards shape"
    )


def _timestamp(value) -> str | None:
    """Leave missing or invalid provider times unavailable."""

    try:
        return snapshot_time(value).isoformat()
    except ValueError:
        return None


def rewards_summary(envelope, mint) -> dict[str, Any]:
    """Translate reward units exactly and preserve zero measurements."""

    data = envelope["data"]
    quote = data.get("quote")
    rewards = data.get("rewards")
    if (
        data.get("mint") != mint
        or data.get("mode") != "reward"
        or not isinstance(quote, dict)
        or not isinstance(rewards, dict)
    ):
        raise ValueError("Expected an exact reward-mode coin")
    Pubkey.from_string(quote["mint"])
    decimals = quote.get("decimals")
    distributed = rewards.get("distributedRaw")
    amount = token_amount(distributed, decimals)
    undistributed = rewards.get("undistributedRaw")
    pending = (
        token_amount(undistributed, decimals)
        if undistributed is not None
        else None
    )
    for name in ("payoutCount", "holderCount"):
        count = rewards.get(name)
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Invalid reward count")
    symbol = quote.get("symbol")
    if symbol is not None and not isinstance(symbol, str):
        raise ValueError("Invalid reward symbol")
    meta = envelope.get("meta")
    generated = meta.get("generatedAt") if isinstance(meta, dict) else None
    return {
        "mint": mint,
        "mode": "reward",
        "reward_mint": quote["mint"],
        "reward_symbol": symbol,
        "decimals": decimals,
        "distributed_raw": str(raw_amount(distributed)),
        "distributed_tokens": amount,
        "undistributed_raw": (
            str(raw_amount(undistributed))
            if undistributed is not None
            else None
        ),
        "undistributed_tokens": pending,
        "payout_count": rewards.get("payoutCount"),
        "holder_count": rewards.get("holderCount"),
        "last_payout_at": _timestamp(rewards.get("lastPayoutAt")),
        "provider_generated_at": _timestamp(generated),
    }
