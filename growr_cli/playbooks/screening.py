"""Validate screening criteria and rank sourced observations exactly."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

NUMERIC_FIELDS = {
    "market_cap_usd",
    "liquidity_usd",
    "volume_24h_usd",
    "holder_count",
    "organic_score",
    "social_score",
    "first_pool_age_hours",
    "top_20_accounts_pct",
}
BOOLEAN_FIELDS = {
    "has_website",
    "has_social",
    "verified",
    "initialized_mint",
    "mint_authority_revoked",
    "freeze_authority_revoked",
}
RPC_FIELDS = {
    "initialized_mint",
    "mint_authority_revoked",
    "freeze_authority_revoked",
    "top_20_accounts_pct",
}
FIELDS = NUMERIC_FIELDS | BOOLEAN_FIELDS | {"category"}
OPERATORS = {"eq", "gte", "lte", "gt", "lt"}


def decimal_value(value) -> Decimal | None:
    """Read bounded finite decimal values without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value)
    if len(text) > 128:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number.adjusted()) > 308:
        return None
    return number


def timestamp(value) -> datetime | None:
    """Accept only timezone-aware observation times."""

    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.utcoffset() is not None else None


def validate_requirement(rule) -> dict[str, Any]:
    """Validate supported fields, operations and exact thresholds."""

    if not isinstance(rule, dict) or set(rule) != {"field", "op", "value"}:
        raise ValueError("Requirements need field, op and value")
    name, operation, value = rule["field"], rule["op"], rule["value"]
    if not isinstance(name, str) or name not in FIELDS:
        raise ValueError("Unsupported screening field")
    if not isinstance(operation, str) or operation not in OPERATORS:
        raise ValueError("Unsupported screening operator")
    if name in NUMERIC_FIELDS:
        number = decimal_value(value)
        if number is None or number < 0:
            raise ValueError(
                "Numeric thresholds must be finite and nonnegative"
            )
        value = str(number)
    elif operation != "eq":
        raise ValueError("Boolean and category fields support only eq")
    elif name in BOOLEAN_FIELDS and type(value) is not bool:
        raise ValueError("Boolean criteria require true or false")
    elif name == "category" and value not in (
        "xstock",
        "prestock",
        "custom",
        "collectibles",
        "currencies",
        "leverage",
    ):
        raise ValueError("Unsupported Stonkfun quote category")
    return {"field": name, "op": operation, "value": value}


def validate_ranking(rules) -> list[dict[str, str]]:
    """Preserve explicit numeric priorities and reject duplicates."""

    if not isinstance(rules, list) or len(rules) > len(NUMERIC_FIELDS):
        raise ValueError("Ranking must be a bounded list")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"field", "direction"}:
            raise ValueError("Ranking needs field and direction")
        name = rule["field"]
        if not isinstance(name, str) or name not in NUMERIC_FIELDS:
            raise ValueError("Only numeric fields can be ranked")
        if rule["direction"] not in ("asc", "desc") or name in seen:
            raise ValueError("Invalid or duplicate ranking priority")
        seen.add(name)
    return rules


def validate_criteria(value) -> dict[str, Any]:
    """Normalize the versioned input before any child commands run."""

    allowed = {
        "criteria_version",
        "requirements",
        "ranking",
        "max_age_seconds",
        "verify_on_chain",
    }
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Unknown criteria settings")
    if value.get("criteria_version") != "1.0":
        raise ValueError("Expected criteria_version 1.0")
    rules = value.get("requirements", [])
    if not isinstance(rules, list) or len(rules) > 30:
        raise ValueError("At most 30 requirements are supported")
    age = value.get("max_age_seconds", 900)
    verify = value.get("verify_on_chain", True)
    if type(age) is not int or not 1 <= age <= 604800:
        raise ValueError("max_age_seconds must be between 1 and 604800")
    if type(verify) is not bool:
        raise ValueError("verify_on_chain must be a boolean")
    return {
        "criteria_version": "1.0",
        "requirements": [validate_requirement(rule) for rule in rules],
        "ranking": validate_ranking(value.get("ranking", [])),
        "max_age_seconds": age,
        "verify_on_chain": verify,
    }


def requirements(criteria) -> list[dict[str, Any]]:
    """Make the default RPC mint validation an explicit requirement."""

    rules = list(criteria["requirements"])
    if criteria["verify_on_chain"]:
        rules.insert(
            0,
            {
                "field": "initialized_mint",
                "op": "eq",
                "value": True,
            },
        )
    return rules


def select_observation(rows, field, as_of, max_age) -> dict[str, Any]:
    """Require fresh evidence; keep conflicting pool values unknown."""

    candidates = [row for row in rows if row["field"] == field]
    if not candidates:
        return {"value": None, "reason": "missing", "evidence": []}
    usable = []
    for row in candidates:
        observed = timestamp(row["observed_at"])
        if observed is None:
            continue
        age = (as_of - observed).total_seconds()
        if 0 <= age <= max_age and row["value"] is not None:
            usable.append(row)
    if not usable:
        return {
            "value": None,
            "reason": "missing_invalid_or_stale",
            "evidence": candidates,
        }
    # Prefer Jupiter token market data over Stonkfun pool measurements.
    # Preserve pools that were observed on different pages.
    priority = min(row["priority"] for row in usable)
    usable = [row for row in usable if row["priority"] == priority]
    usable = latest_per_entity(usable)
    values = {
        Decimal(row["value"]) if field in NUMERIC_FIELDS else row["value"]
        for row in usable
    }
    if len(values) != 1:
        return {
            "value": None,
            "reason": "conflicting_values",
            "evidence": usable,
        }
    return {"value": usable[0]["value"], "reason": None, "evidence": usable}


def latest_per_entity(rows) -> list[dict[str, Any]]:
    """Select the latest observation separately for each source/pool."""

    latest = {
        (row["source"], row["scope"], row["pool"]): float("-inf")
        for row in rows
    }
    for row in rows:
        key = (row["source"], row["scope"], row["pool"])
        observed = timestamp(row["observed_at"])
        if observed is None:
            continue
        moment = observed.timestamp()
        latest[key] = max(moment, latest.get(key, moment))
    return [
        row
        for row in rows
        if observation_time(row)
        == latest.get((row["source"], row["scope"], row["pool"]))
    ]


def observation_time(row) -> float | None:
    """Compare timestamps after normalizing their timezones."""

    observed = timestamp(row["observed_at"])
    return observed.timestamp() if observed is not None else None


def compare(value, rule) -> bool:
    """Compare normalized values with exact decimal thresholds."""

    target = rule["value"]
    if rule["field"] in NUMERIC_FIELDS:
        value, target = Decimal(value), Decimal(target)
    checks = {
        "eq": lambda: value == target,
        "gte": lambda: value >= target,
        "lte": lambda: value <= target,
        "gt": lambda: value > target,
        "lt": lambda: value < target,
    }
    return checks[rule["op"]]()


def evaluate(candidate, criteria, as_of) -> dict[str, Any]:
    """Return auditable conditions and ranking inputs for one mint."""

    rules = requirements(criteria)
    names = {rule["field"] for rule in rules + criteria["ranking"]}
    selected = {
        name: select_observation(
            candidate["observations"], name, as_of, criteria["max_age_seconds"]
        )
        for name in sorted(names)
    }
    checks = []
    for rule in rules:
        observation = selected[rule["field"]]
        value = observation["value"]
        outcome = "unknown"
        if value is not None:
            outcome = "pass" if compare(value, rule) else "fail"
        checks.append(
            {
                **rule,
                **observation,
                "expected": rule["value"],
                "outcome": outcome,
            }
        )
    outcomes = {check["outcome"] for check in checks}
    decision = "unknown" if "unknown" in outcomes else "pass"
    if "fail" in outcomes:
        decision = "fail"
    ranking = [
        {**rule, **selected[rule["field"]]} for rule in criteria["ranking"]
    ]
    return {
        **candidate,
        "decision": decision,
        "requirements": checks,
        "ranking": ranking,
        "ranking_complete": all(row["value"] is not None for row in ranking),
    }


def rank_key(candidate) -> tuple[Any, ...]:
    """Sort lexicographically, missing values last, then exact mint."""

    result = []
    for row in candidate["ranking"]:
        number = decimal_value(row["value"])
        value = number if number is not None else Decimal(0)
        signed = value.copy_negate() if row["direction"] == "desc" else value
        result.append((number is None, signed))
    return (not candidate["ranking_complete"], *result, candidate["mint"])
