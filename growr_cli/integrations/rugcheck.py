"""Rugcheck endpoints and response interpretation."""

from __future__ import annotations

from typing import Any

from growr_cli import settings
from growr_cli.integrations.http import provider_result
from growr_cli.models import EnrichmentResult


class RugcheckClient:
    """Read rugcheck data without owning workflow decisions."""

    def __init__(self, http) -> None:
        """Use the injected transport; its creator owns cleanup."""

        self.http = http

    def _get_single(self, mint) -> tuple[dict[str, Any] | None, str | None]:
        """Get Rugcheck's report. It is useful evidence, not scripture.

        Args:
            mint: Token mint address.

        Returns:
            ``(report, None)`` on success, ``(None, error)`` on failure,
            or ``(None, None)`` when the provider returned no usable
            report.
        """

        url = "%s/tokens/%s/report" % (settings.RUGCHECK_API_URL, mint)
        data, error = self.http.get_json(url)
        if error:
            return None, error
        if data is None:
            return None, None
        if not isinstance(data, dict):
            return None, "unexpected response shape"
        return data, None

    def get_report(self, mint) -> EnrichmentResult:
        """Return single-token data with explicit coverage."""

        data, error = self._get_single(mint)
        if error:
            return provider_result("failed", detail=error)
        return provider_result("success" if data else "no_data", data)


def report_summary(report) -> dict[str, Any]:
    """Normalize provider-reported Rugcheck fields."""

    token_meta = report.get("tokenMeta")
    risks = report.get("risks")
    risk_count = len(risks) if isinstance(risks, list) else 0
    return {
        "name": token_meta.get("name")
        if isinstance(token_meta, dict)
        else None,
        "symbol": token_meta.get("symbol")
        if isinstance(token_meta, dict)
        else None,
        "score": report.get("score")
        if report.get("score") is not None
        else report.get("score_normalised"),
        "risk_count": risk_count,
        "creator": report.get("creator"),
    }
