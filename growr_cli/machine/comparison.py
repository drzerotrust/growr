"""Read a previous Growr reward snapshot without changing its file."""

import json
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from growr_cli.analysis.metrics import mapping
from growr_cli.analysis.rewards import validate_snapshot


def _reject_constant(value) -> None:
    raise ValueError("Non-finite JSON constant")


def load_reward_snapshot(filename, mint) -> dict[str, Any]:
    """Read a saved report and extract comparable reward data."""

    try:
        path = Path(filename)
        if not path.is_file():
            raise ValueError("Not a report file")
        with path.open(encoding="utf-8") as stream:
            document = json.load(stream, parse_constant=_reject_constant)
        return _snapshot(document, mint)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        # Neither local filenames nor arbitrary file contents belong in
        # diagnostics, request metadata or the next report's raw output.
        raise ValueError(
            "Invalid --compare-to report; use a schema 2.2 token report "
            "with successful timestamped rewards for the same mint"
        ) from None


def _snapshot(document, mint) -> dict[str, Any]:
    if not isinstance(document, dict) or (
        document.get("schema_version") != "2.2"
        or document.get("status") not in ("success", "partial")
        or document.get("error") is not None
    ):
        raise ValueError("Expected a usable schema 2.2 report")
    if mapping(document.get("tool")).get("name") != "growr":
        raise ValueError("Expected a Growr report")
    request = mapping(document.get("request"))
    if (
        request.get("command") != "token"
        or request.get("target") != mint
        or mapping(request.get("options")).get("stonk") is not True
    ):
        raise ValueError("Expected a Stonkfun token scan for this mint")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("Expected one token record")
    record = records[0]
    if not isinstance(record, dict) or record.get("kind") != "token":
        raise ValueError("Expected a token record")
    identity = mapping(record.get("identity"))
    if (
        identity.get("mint") != mint
        or identity.get("address") != mint
        or identity.get("chain") != "solana"
    ):
        raise ValueError("Expected the same Solana mint")
    return _reward_snapshot(record, mint)


def _reward_snapshot(record, mint) -> dict[str, Any]:
    """Require successful reward coverage for saved totals."""

    outcomes = record.get("coverage", [])
    if not isinstance(outcomes, list):
        raise ValueError("Missing reward coverage")
    rewards = [
        item
        for item in outcomes
        if isinstance(item, dict)
        and item.get("source") == "stonks"
        and item.get("operation") == "rewards"
    ]
    if len(rewards) != 1 or rewards[0].get("status") != "success":
        raise ValueError("Previous reward retrieval did not succeed")
    metrics = mapping(mapping(record.get("metrics")).get("stonks_rewards"))
    if metrics.get("source") != "stonks" or metrics.get("scope") != "token":
        raise ValueError("Expected Stonks token reward measurements")
    values = mapping(metrics.get("values"))
    validate_snapshot(values)
    if values["mint"] != mint:
        raise ValueError("Reward snapshot belongs to another mint")
    Pubkey.from_string(values["reward_mint"])
    # Carry only inputs to the calculation, never provider messages or
    # unrelated records from the file supplied by a caller.
    return {
        name: values[name]
        for name in (
            "mint",
            "mode",
            "reward_mint",
            "decimals",
            "distributed_raw",
            "provider_generated_at",
        )
    }
