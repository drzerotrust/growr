"""Transaction and address-history facts for machine consumers."""

from typing import Any

from growr_cli.machine.schema_records import COUNT, TEXT, VALUE, fields


def transaction_fact() -> dict[str, Any]:
    """Document exact units, execution outcome and recording gaps."""

    return fields(
        {
            "signature": {"type": "string"},
            "slot": COUNT,
            "block_time": COUNT,
            "version": {"type": ["string", "integer", "null"]},
            "execution_status": {"enum": ["success", "failed", "unknown"]},
            "fee_lamports": {
                "type": ["string", "null"],
                "pattern": "^[0-9]+$",
            },
            "fee_payer": TEXT,
            "signers": {"type": "array", "items": {"type": "string"}},
            "events": {"type": "array", "items": {"type": "object"}},
            "recording": {
                "type": "object",
                "additionalProperties": {"type": "boolean"},
            },
        }
    )


def history_facts() -> dict[str, Any]:
    """Describe one bounded page; unavailable bodies stay null."""

    entry = fields(
        {
            "signature": {"type": "string"},
            "slot": COUNT,
            "block_time": COUNT,
            "error": VALUE,
            "execution_status": {"enum": ["success", "failed"]},
            "detail_status": {
                "enum": ["success", "partial", "failed", "skipped"]
            },
            "transaction": {"anyOf": [transaction_fact(), {"type": "null"}]},
        }
    )
    entry["required"] = list(entry["properties"])
    return fields(
        {
            "scope": {"const": "address_references"},
            "entries": {"type": "array", "items": entry, "maxItems": 100},
            "pagination": {"type": "object"},
        }
    )


def transaction_variants() -> list[dict[str, Any]]:
    """Register history and transaction identities separately."""

    return [
        {
            "properties": {
                "kind": {"const": "history"},
                "facts": history_facts(),
                "identity": {"required": ["chain", "address"]},
            }
        },
        {
            "properties": {
                "kind": {"const": "transaction"},
                "identity": {"required": ["chain", "signature"]},
                "facts": fields(
                    {
                        "available": {"type": "boolean"},
                        "transaction": {
                            "anyOf": [transaction_fact(), {"type": "null"}]
                        },
                    }
                ),
            }
        },
    ]
