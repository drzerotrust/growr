"""Discoverable JSON Schema for growr's version 2 machine contract."""

from typing import Any

from growr_cli.machine.schema_records import record_variants
from growr_cli.machine.schema_rewards import reward_metrics


def obj(properties, required=None, *, additional=False) -> dict[str, Any]:
    """Describe a JSON object with explicit required fields."""

    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": additional,
    }


def response_schema() -> dict[str, Any]:
    """Return the schema without configuration or network access."""

    text = {"type": "string"}
    nullable_text = {"type": ["string", "null"]}
    timestamp = {"type": "string", "format": "date-time"}
    outcomes = {"type": "array", "items": {"$ref": "#/$defs/coverage"}}
    values = {
        "type": "object",
        "additionalProperties": {"$ref": "#/$defs/value"},
    }
    identity = obj(
        dict.fromkeys(
            ("chain", "address", "mint", "pool", "owner", "name", "symbol"),
            nullable_text,
        ),
        [],
        additional=False,
    )
    finding = obj(
        dict.fromkeys(("severity", "label", "detail", "source"), text)
    )
    link = obj(
        {
            "kind": {"enum": ["website", "social"]},
            "platform": nullable_text,
            "url": {"type": "string", "format": "uri"},
            "sources": {"type": "array", "items": text},
        }
    )
    social = obj(
        {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "max_score": {"const": 100},
            "has_website": {"type": "boolean"},
            "platforms": {"type": "array", "items": text, "uniqueItems": True},
            "links": {"type": "array", "items": link},
            "coverage": {
                "type": "object",
                "additionalProperties": {
                    "enum": ["success", "failed", "no_data", "not_configured"]
                },
            },
        }
    )
    record = obj(
        {
            "kind": {
                "enum": [
                    "token",
                    "wallet",
                    "token_account",
                    "pool",
                    "token_discovery",
                ]
            },
            "identity": identity,
            "facts": values,
            "metrics": {**values, "properties": reward_metrics()},
            "findings": {"type": "array", "items": finding},
            "social": {"anyOf": [social, {"type": "null"}]},
            "coverage": outcomes,
            "on_chain": {
                "anyOf": [{"$ref": "#/$defs/record"}, {"type": "null"}]
            },
            "raw": values,
        },
        [
            "kind",
            "identity",
            "facts",
            "metrics",
            "findings",
            "social",
            "coverage",
            "on_chain",
        ],
    )
    record["oneOf"] = record_variants()
    outcome = obj(
        {
            "source": text,
            "operation": text,
            "status": {
                "enum": [
                    "success",
                    "failed",
                    "partial",
                    "no_data",
                    "not_configured",
                    "skipped",
                ]
            },
            "detail": text,
            "fetched_at": {"anyOf": [timestamp, {"type": "null"}]},
            "counts": {
                "type": "object",
                "additionalProperties": {"type": "integer", "minimum": 0},
            },
        },
        ["source", "operation", "status", "detail", "fetched_at"],
    )
    error = obj(
        {
            "code": {
                "enum": [
                    "INVALID_ARGUMENTS",
                    "RPC_ERROR",
                    "EXECUTION_FAILED",
                    "INTERNAL_ERROR",
                ]
            },
            "message": text,
        }
    )
    schema = obj(
        {
            "schema_version": {"const": "2.2"},
            "tool": obj({"name": {"const": "growr"}, "version": text}),
            "run": obj(
                {
                    "id": {"type": "string", "format": "uuid"},
                    "started_at": timestamp,
                    "completed_at": timestamp,
                    "elapsed_ms": {"type": "number", "minimum": 0},
                }
            ),
            "request": obj(
                {
                    "command": {
                        "enum": [
                            "token",
                            "wallet",
                            "token-account",
                            "list",
                            "search",
                            None,
                        ]
                    },
                    "target": nullable_text,
                    "options": values,
                    "rpc": nullable_text,
                }
            ),
            "status": {"enum": ["success", "partial", "no_data", "error"]},
            "records": {"type": "array", "items": {"$ref": "#/$defs/record"}},
            "pagination": {"anyOf": [values, {"type": "null"}]},
            "coverage": outcomes,
            "error": {"anyOf": [error, {"type": "null"}]},
            "raw": values,
        },
        [
            "schema_version",
            "tool",
            "run",
            "request",
            "status",
            "records",
            "pagination",
            "coverage",
            "error",
        ],
    )
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "growr response 2.2",
            "$defs": {
                "coverage": outcome,
                "record": record,
                "value": {
                    "anyOf": [
                        {"type": ["string", "number", "boolean", "null"]},
                        {"type": "array", "items": {"$ref": "#/$defs/value"}},
                        values,
                    ]
                },
            },
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "error"}}},
                    "then": {
                        "properties": {
                            "error": error,
                            "records": {"maxItems": 0},
                        }
                    },
                    "else": {"properties": {"error": {"type": "null"}}},
                }
            ],
        }
    )
    return schema
