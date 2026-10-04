"""Validate activity records and child request counts."""

from typing import Any

from solders.signature import Signature


def validate_activity(record, command, request) -> None:
    """Reject mismatched history windows or transaction bodies."""

    facts = record["facts"]
    if command[0] == "transaction":
        body = facts["transaction"]
        if body is not None and body["signature"] != command[1]:
            raise ValueError("Mismatched transaction evidence")
    if command[0] != "history":
        return
    options = request["options"]
    before = None
    if "--before" in command:
        before_position = command.index("--before") + 1
        before = command[before_position]
    limit_position = command.index("--limit") + 1
    limit = int(command[limit_position])
    if (
        options.get("details") is not False
        or options.get("limit") != limit
        or options.get("before") != before
    ):
        raise ValueError("Mismatched history scope")
    validate_history_facts(facts, limit, before)


def validate_history_facts(facts, limit, before) -> None:
    """Require bounded reference rows and a usable continuation."""

    rows = facts["entries"]
    page = facts["pagination"]
    if (
        facts["scope"] != "address_references"
        or not isinstance(rows, list)
        or len(rows) > limit
    ):
        raise ValueError("Invalid history references")
    seen = set()
    for row in rows:
        signature = str(Signature.from_string(row["signature"]))
        if (
            signature in seen
            or type(row["slot"]) is not int
            or row["slot"] < 0
        ):
            raise ValueError("Invalid history entry")
        seen.add(signature)
    if page["limit"] != limit or page["before"] != before:
        raise ValueError("Mismatched continuation window")
    cursor = page["next_before"]
    if cursor is not None:
        Signature.from_string(cursor)
        if cursor not in seen:
            raise ValueError("Continuation is outside the returned page")


def measured_requests(run) -> dict[str, Any] | None:
    """Copy validated counters from child run metadata."""

    requests = run.get("requests")
    if requests is None:
        return None
    counters = {}
    for transport in ("rpc", "http"):
        counts = {}
        for key in ("attempted", "failed", "blocked", "limit"):
            value = requests[transport][key]
            if type(value) is not int or value < 0:
                raise ValueError("Invalid measured request counts")
            counts[key] = value
        counters[transport] = counts
    return counters


def measured_totals(scans) -> dict[str, Any]:
    """Separate measured attempts from children with unknown counts."""

    rpc_attempts = 0
    http_attempts = 0
    unmeasured_children = 0
    for scan in scans:
        requests = scan.get("requests")
        if requests is None:
            unmeasured_children += 1
            continue
        rpc_attempts += requests["rpc"]["attempted"]
        http_attempts += requests["http"]["attempted"]
    return {
        "rpc_attempts_observed": rpc_attempts,
        "http_attempts_observed": http_attempts,
        "unmeasured_children": unmeasured_children,
        "complete": unmeasured_children == 0,
    }
