"""Bounded JSON input and public report validation for screening."""

import json
from copy import deepcopy
from typing import Any

from growr_cli.playbooks.runner import (
    finite_number,
    reject_constant,
    scan_record,
    valid_address,
    validate_document,
)
from growr_cli.playbooks.screen_observations import validate_record
from growr_cli.playbooks.screening import timestamp


def unique_keys(pairs) -> dict[str, Any]:
    """Reject duplicate keys instead of silently changing criteria."""

    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_json(path, limit=10 * 1024 * 1024) -> dict[str, Any]:
    """Read a size-bounded file without exposing its text on failure."""

    try:
        with open(path, "rb") as stream:
            payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("JSON input exceeds its size limit")
        result = json.loads(
            payload,
            parse_constant=reject_constant,
            parse_float=finite_number,
            object_pairs_hook=unique_keys,
        )
    except (OSError, UnicodeError, RecursionError) as error:
        raise ValueError("Unable to read JSON input") from error
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def discovery_document(document, expected=None) -> dict[str, Any]:
    """Match discovery scope before accepting any candidate records."""

    validate_document(document)
    request = document["request"]
    options = request["options"]
    if request["command"] not in {"list", "search"}:
        raise ValueError("Expected a Growr discovery report")
    source = options.get("source")
    if source not in {"jupiter", "stonks"} or request["target"] is not None:
        raise ValueError("Invalid discovery source or target")
    if expected is not None:
        validate_request(request, expected)
    records = document["records"]
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("Invalid discovery records")
    for record in records:
        validate_record(record)
        if record["facts"]["source"] != source or record["kind"] == "token":
            raise ValueError("Mismatched discovery record")
        validate_nested_rpc(record, options.get("on_chain", False))
    if not isinstance(document["coverage"], list):
        raise ValueError("Invalid discovery coverage")
    if timestamp(document["run"]["completed_at"]) is None:
        raise ValueError("Missing discovery retrieval time")
    return document


def validate_nested_rpc(record, enabled) -> None:
    """Accept nested mint facts only for explicit on-chain discovery."""

    nested = record.get("on_chain")
    if nested is None:
        return
    validate_record(nested)
    if (
        enabled is not True
        or nested["kind"] != "token"
        or nested["identity"]["mint"] != record["identity"]["mint"]
    ):
        raise ValueError("Unexpected nested RPC evidence")


def validate_request(request, expected) -> None:
    """Match the child discovery command and selected options."""

    command, options = expected
    if request["command"] != command or request.get("rpc") is not None:
        raise ValueError("Mismatched discovery command")
    if any(
        request["options"].get(key) != value for key, value in options.items()
    ):
        raise ValueError("Mismatched discovery options")


def token_document(document, mint) -> dict[str, Any]:
    """Require the exact requested mint's public RPC record."""

    record = scan_record(document, "token", mint)
    validate_record(record)
    return document


def append_document(
    evidence, document, scan_index=None
) -> list[dict[str, Any]]:
    """Retain public records and nested RPC evidence, excluding raw."""

    retrieved = document["run"]["completed_at"]
    for original in document["records"]:
        record = deepcopy(original)
        record.pop("raw", None)
        on_chain = record.pop("on_chain", None)
        evidence.append(
            {
                "record": record,
                "retrieved_at": retrieved,
                "scan_index": scan_index,
            }
        )
        if on_chain is not None:
            validate_record(on_chain)
            if on_chain["identity"]["mint"] != record["identity"]["mint"]:
                raise ValueError("Mismatched nested mint evidence")
            on_chain.pop("raw", None)
            evidence.append(
                {
                    "record": on_chain,
                    "retrieved_at": retrieved,
                    "scan_index": scan_index,
                }
            )
    return evidence


def saved_evidence(
    document,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Read discovery or screen evidence for offline reranking."""

    if document.get("schema_version") == "2.2":
        discovery_document(document)
        evidence = append_document([], document)
        scope = {
            "discovery_request": document["request"]["options"],
            "source_status": document["status"],
            "source_run": document["run"],
        }
        return evidence, evidence_mints(evidence), scope
    if (
        document.get("playbook_version") != "1.1"
        or document.get("playbook") != "token_screen"
        or document.get("screening_version") != "1.0"
        or document.get("status") not in {"success", "partial", "no_data"}
    ):
        raise ValueError("Expected discovery 2.2 or token_screen 1.0 evidence")
    evidence = document["evidence"]
    mints = document["scope"]["selected_mints"]
    if not isinstance(evidence, list) or len(evidence) > 10000:
        raise ValueError("Invalid saved evidence collection")
    if not isinstance(mints, list) or len(mints) > 100:
        raise ValueError("Invalid saved candidate scope")
    if not all(valid_address(mint) for mint in mints) or len(
        set(mints)
    ) != len(mints):
        raise ValueError("Invalid or duplicate saved mints")
    for entry in evidence:
        validate_record(entry["record"])
        if timestamp(entry["retrieved_at"]) is None:
            raise ValueError("Invalid saved retrieval time")
        if entry["record"]["identity"]["mint"] not in mints:
            raise ValueError("Evidence outside the selected candidate scope")
    return (
        evidence,
        mints,
        {
            "source_as_of": document.get("as_of"),
            "source_status": document["status"],
            "source_scope": document["scope"],
            "source_scans": document.get("scans")
            or document["scope"].get("source_scans", []),
        },
    )


def evidence_mints(evidence) -> list[str]:
    """Group repeated mints in their original discovery order."""

    return list(
        dict.fromkeys(
            entry["record"]["identity"]["mint"] for entry in evidence
        )
    )
