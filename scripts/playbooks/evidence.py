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
    before = (
        command[command.index("--before") + 1]
        if "--before" in command
        else None
    )
    limit = int(command[command.index("--limit") + 1])
    if (
        options.get("details") is not False
        or options.get("limit") != limit
        or options.get("before") != before
    ):
        raise ValueError("Mismatched history scope")
    validate_history_facts(facts, limit, before)


def validate_history_facts(facts, limit, before) -> None:
    """Require bounded reference rows and a usable continuation."""

    rows, page = facts["entries"], facts["pagination"]
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
        counts = {
            key: requests[transport][key]
            for key in ("attempted", "failed", "blocked", "limit")
        }
        if any(
            type(value) is not int or value < 0 for value in counts.values()
        ):
            raise ValueError("Invalid measured request counts")
        counters[transport] = counts
    return counters


def measured_totals(scans) -> dict[str, Any]:
    """Separate measured attempts from children with unknown counts."""

    measured = [
        row["requests"] for row in scans if row.get("requests") is not None
    ]
    return {
        "rpc_attempts_observed": sum(
            row["rpc"]["attempted"] for row in measured
        ),
        "http_attempts_observed": sum(
            row["http"]["attempted"] for row in measured
        ),
        "unmeasured_children": len(scans) - len(measured),
        "complete": len(scans) == len(measured),
    }
