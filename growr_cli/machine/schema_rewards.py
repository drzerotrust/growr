"""Schema contracts for reward totals and interval comparisons."""

from typing import Any

RAW = {"type": "string", "pattern": "^[0-9]+$"}
AMOUNT = {"type": "string", "pattern": "^[0-9]+(?:\\.[0-9]+)?$"}
TEXT = {"type": "string"}
OPTIONAL_TEXT = {"type": ["string", "null"]}
DECIMALS = {"type": "integer", "minimum": 0, "maximum": 255}
COUNT = {"type": ["integer", "null"], "minimum": 0}
TIME = {"type": "string", "format": "date-time"}
OPTIONAL_TIME = {"anyOf": [TIME, {"type": "null"}]}


def _metric(source, properties) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source": {"const": source},
            "scope": {"const": "token"},
            "values": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
        "required": ["source", "scope", "values"],
        "additionalProperties": False,
    }


def reward_metrics() -> dict[str, Any]:
    """Keep exact token amounts distinct from provider floats."""

    identity = {
        "mint": TEXT,
        "reward_mint": TEXT,
        "reward_symbol": OPTIONAL_TEXT,
        "decimals": DECIMALS,
    }
    return {
        "stonks_rewards": _metric(
            "stonks",
            {
                **identity,
                "mode": {"const": "reward"},
                "distributed_raw": RAW,
                "distributed_tokens": AMOUNT,
                "undistributed_raw": {"anyOf": [RAW, {"type": "null"}]},
                "undistributed_tokens": {"anyOf": [AMOUNT, {"type": "null"}]},
                "payout_count": COUNT,
                "holder_count": COUNT,
                "last_payout_at": OPTIONAL_TIME,
                "provider_generated_at": OPTIONAL_TIME,
            },
        ),
        "reward_comparison": _metric(
            "growr",
            {
                **identity,
                "previous_generated_at": TIME,
                "current_generated_at": TIME,
                "elapsed_seconds": {"type": "number", "exclusiveMinimum": 0},
                "distributed_delta_raw": RAW,
                "distributed_delta_tokens": AMOUNT,
                "normalized_daily_tokens": AMOUNT,
            },
        ),
    }
