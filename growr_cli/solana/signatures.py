"""Translate signature observations without exposing SDK objects."""

import json
from typing import Any

from solders.signature import Signature


def signature_records(entries) -> list[dict[str, Any]]:
    """Keep execution status and chronology for validated signatures."""

    records = []
    seen = set()
    for entry in entries:
        data = json.loads(entry.to_json())
        signature = str(Signature.from_string(data["signature"]))
        if signature in seen:
            continue
        seen.add(signature)
        records.append(
            {
                "signature": signature,
                "slot": data["slot"],
                "block_time": data.get("blockTime"),
                "error": data["err"],
                "execution_status": "success"
                if data["err"] is None
                else "failed",
                "confirmation_status": data.get("confirmationStatus"),
                "memo": data.get("memo"),
            }
        )
    return records
