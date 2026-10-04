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
    name = rule["field"]
    operation = rule["op"]
    value = rule["value"]
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

    validated_rules = []
    for rule in rules:
        validated_rules.append(validate_requirement(rule))
    return {
        "criteria_version": "1.0",
        "requirements": validated_rules,
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

    candidates = []
    for row in rows:
        if row["field"] == field:
            candidates.append(row)
    if not candidates:
        return {"value": None, "reason": "missing", "evidence": []}
    usable = fresh_observations(candidates, as_of, max_age)
    if not usable:
        return {
            "value": None,
            "reason": "missing_invalid_or_stale",
            "evidence": candidates,
        }
    # Prefer Jupiter token market data over Stonkfun pool measurements.
    # Preserve pools that were observed on different pages.
    usable = preferred_observations(usable)
    usable = latest_per_entity(usable)
    values = set()
    for row in usable:
        value = row["value"]
        if field in NUMERIC_FIELDS:
            value = Decimal(value)
        values.add(value)
    if len(values) != 1:
        return {
            "value": None,
            "reason": "conflicting_values",
            "evidence": usable,
        }
    return {"value": usable[0]["value"], "reason": None, "evidence": usable}


def fresh_observations(rows, as_of, max_age) -> list[dict[str, Any]]:
    """Keep known values with valid timestamps inside the age window."""

    usable = []
    for row in rows:
        observed = timestamp(row["observed_at"])
        if observed is None or row["value"] is None:
            continue
        age_seconds = (as_of - observed).total_seconds()
        if 0 <= age_seconds <= max_age:
            usable.append(row)
    return usable


def preferred_observations(rows) -> list[dict[str, Any]]:
    """Keep all observations at the best available source priority."""

    best_priority = rows[0]["priority"]
    for row in rows:
        best_priority = min(best_priority, row["priority"])

    selected = []
    for row in rows:
        if row["priority"] == best_priority:
            selected.append(row)
    return selected


def latest_per_entity(rows) -> list[dict[str, Any]]:
    """Select the latest observation separately for each source/pool."""

    latest = {}
    for row in rows:
        key = (row["source"], row["scope"], row["pool"])
        if key not in latest:
            latest[key] = float("-inf")
        moment = observation_time(row)
        if moment is None:
            continue
        if moment > latest[key]:
            latest[key] = moment

    # Preserve simultaneous observations so conflicts remain detectable.
    selected = []
    for row in rows:
        key = (row["source"], row["scope"], row["pool"])
        latest_time = latest.get(key, float("-inf"))
        if observation_time(row) == latest_time:
            selected.append(row)
    return selected


def observation_time(row) -> float | None:
    """Compare timestamps after normalizing their timezones."""

    observed = timestamp(row["observed_at"])
    return observed.timestamp() if observed is not None else None


def compare(value, rule) -> bool:
    """Compare normalized values with exact decimal thresholds."""

    target = rule["value"]
    if rule["field"] in NUMERIC_FIELDS:
        value = Decimal(value)
        target = Decimal(target)

    operation = rule["op"]
    if operation == "eq":
        return value == target
    if operation == "gte":
        return value >= target
    if operation == "lte":
        return value <= target
    if operation == "gt":
        return value > target
    if operation == "lt":
        return value < target
    raise KeyError(operation)


def evaluate(candidate, criteria, as_of) -> dict[str, Any]:
    """Return auditable conditions and ranking inputs for one mint."""

    rules = requirements(criteria)
    names = set()
    for rule in rules + criteria["ranking"]:
        names.add(rule["field"])

    # Resolve each measurement once for both filtering and ranking.
    selected = {}
    for name in sorted(names):
        selected[name] = select_observation(
            candidate["observations"], name, as_of, criteria["max_age_seconds"]
        )

    checks = []
    outcomes = set()
    for rule in rules:
        observation = selected[rule["field"]]
        value = observation["value"]
        outcome = "unknown"
        if value is not None:
            outcome = "pass" if compare(value, rule) else "fail"
        check = dict(rule)
        check.update(observation)
        check["expected"] = rule["value"]
        check["outcome"] = outcome
        checks.append(check)
        outcomes.add(outcome)

    # A known failure takes precedence over incomplete requirements.
    decision = "unknown" if "unknown" in outcomes else "pass"
    if "fail" in outcomes:
        decision = "fail"
    ranking = []
    ranking_complete = True
    for rule in criteria["ranking"]:
        ranked_field = dict(rule)
        ranked_field.update(selected[rule["field"]])
        ranking.append(ranked_field)
        if ranked_field["value"] is None:
            ranking_complete = False

    result = dict(candidate)
    result["decision"] = decision
    result["requirements"] = checks
    result["ranking"] = ranking
    result["ranking_complete"] = ranking_complete
    return result


def rank_key(candidate) -> tuple[Any, ...]:
    """Sort lexicographically, missing values last, then exact mint."""

    result = []
    for row in candidate["ranking"]:
        number = decimal_value(row["value"])
        value = number if number is not None else Decimal(0)
        signed = value.copy_negate() if row["direction"] == "desc" else value
        result.append((number is None, signed))
    return (not candidate["ranking_complete"], *result, candidate["mint"])
