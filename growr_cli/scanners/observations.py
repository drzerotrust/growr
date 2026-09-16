"""Keep independent optional reads usable when another read fails."""

from typing import Any

from growr_cli.models import ProviderStatus
from growr_cli.solana.signatures import signature_records


def optional_result(future, report, operation):
    """Record a safe coverage gap without discarding other futures."""

    try:
        return future.result()
    except Exception:
        report.providers.append(
            ProviderStatus(
                "rpc", "failed", "RPC observation unavailable", operation
            )
        )
        return None


def activity_fields(signatures, report, operation) -> dict[str, Any]:
    """Distinguish unknown activity from an empty page."""

    records = None
    if signatures is not None:
        try:
            records = signature_records(signatures)
        except (AttributeError, KeyError, TypeError, ValueError):
            report.providers.append(
                ProviderStatus(
                    "rpc",
                    "partial",
                    "Signature records could not be decoded",
                    operation,
                )
            )
    return {
        "recent_signature_count": len(signatures)
        if signatures is not None
        else None,
        "recent_signatures": records,
        "activity_scope": "address_references",
    }
