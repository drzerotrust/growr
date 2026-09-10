"""Attach social evidence without replacing provider record fields."""

from typing import Any

from growr_cli.analysis.metrics import mapping
from growr_cli.analysis.social import social_presence


def attach_social(record, candidates, coverage) -> dict[str, Any]:
    """Return a record copy with additive social analytics."""

    return {
        **record,
        "analytics": {
            **mapping(record.get("analytics")),
            "social": social_presence(candidates, coverage),
        },
    }
