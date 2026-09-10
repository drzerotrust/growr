"""Kind-specific fact schemas for normalized evidence records."""

from typing import Any

VALUE = {"$ref": "#/$defs/value"}
TEXT = {"type": ["string", "null"]}
NUMBER = {"type": ["number", "null"]}
COUNT = {"type": ["integer", "null"], "minimum": 0}
RAW_AMOUNT = {"type": "string", "pattern": "^[0-9]+$"}


def fields(properties) -> dict[str, Any]:
    """Describe known observations and permit JSON extensions."""

    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": VALUE,
    }


def fact_schemas() -> dict[str, Any]:
    """Describe the observations available for each record kind."""

    mint = fields(
        {
            "token_program": TEXT,
            "program_id": TEXT,
            "supply": RAW_AMOUNT,
            "decimals": COUNT,
            "initialized": {"type": "boolean"},
            "mint_authority": TEXT,
            "freeze_authority": TEXT,
            "raw_account_bytes": COUNT,
        }
    )
    account = fields(
        {
            "mint": TEXT,
            "owner": TEXT,
            "raw_amount": RAW_AMOUNT,
            "token_program": TEXT,
            "delegate": TEXT,
            "close_authority": TEXT,
            "state": TEXT,
        }
    )
    holders = fields(
        {
            "top_twenty_percent": NUMBER,
            "top_accounts": {
                "type": "array",
                "items": fields(
                    {
                        "token_account": TEXT,
                        "owner": TEXT,
                        "raw_amount": RAW_AMOUNT,
                        "ui_amount": NUMBER,
                        "percent_of_supply": NUMBER,
                    }
                ),
            },
            "note": TEXT,
        }
    )
    metadata = fields(
        {
            "exists": {"type": "boolean"},
            "address": TEXT,
            "source": TEXT,
            "name": TEXT,
            "symbol": TEXT,
            "uri": TEXT,
            "update_authority": TEXT,
            "warning": TEXT,
        }
    )
    wallet = fields(
        {
            "sol_balance": NUMBER,
            "recent_signature_count": COUNT,
            "token_accounts": fields(
                dict.fromkeys(
                    (
                        "spl_token_account_count",
                        "token_2022_account_count",
                        "total_account_count",
                    ),
                    COUNT,
                )
            ),
        }
    )
    return {
        "token": fields(
            {"mint": mint, "metadata": metadata, "holders": holders}
        ),
        "wallet": wallet,
        "token_account": fields(
            {"token_account": account, "owner_wallet": wallet}
        ),
        "pool": fields(
            dict.fromkeys(
                (
                    "launch_status",
                    "created_at",
                    "graduated_at",
                    "creator",
                    "launchpad",
                    "quote_mint",
                    "quote_name",
                    "quote_symbol",
                    "quote_category",
                    "metadata_uri",
                    "image_url",
                ),
                TEXT,
            )
        ),
        "token_discovery": fields({"description": TEXT, "provider_url": TEXT}),
    }


def record_variants() -> list[dict[str, Any]]:
    """Discriminate record kinds and their required identity keys."""

    variants = []
    for kind, facts in fact_schemas().items():
        required = (
            ["chain", "mint"]
            if kind in {"pool", "token_discovery"}
            else ["chain", "address"]
        )
        variants.append(
            {
                "properties": {
                    "kind": {"const": kind},
                    "facts": facts,
                    "identity": {"required": required},
                },
            }
        )
    return variants
