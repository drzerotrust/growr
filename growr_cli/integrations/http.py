"""HTTP transport, response validation, and coverage results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from growr_cli import __version__
from growr_cli.models import EnrichmentResult


def provider_result(
    status,
    data=None,
    detail="",
) -> EnrichmentResult:
    """Timestamp one provider outcome without replacing missing data."""

    return EnrichmentResult(
        status, datetime.now(timezone.utc).isoformat(), data, detail
    )


class HttpClient:
    """Own a reusable HTTP session for injected integrations."""

    def __init__(self, timeout_seconds) -> None:
        """Configure the session and a timeout for every request."""

        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": f"growr/{__version__}",
            }
        )

    def close(self) -> None:
        """Release pooled HTTP connections."""

        self.session.close()

    def get_json(
        self,
        url,
        params=None,
        headers=None,
        *,
        source="Provider",
    ) -> tuple[Any, str | None]:
        """Fetch JSON with credential-free transport failures."""

        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            # Exception text can expose authenticated URLs or headers.
            return None, f"{source} request failed ({type(error).__name__})"

        if not response.ok:
            status = f"HTTP {response.status_code}"
            detail = (
                status
                if source == "Provider"
                else f"{source} returned {status}"
            )
            return None, detail

        try:
            return response.json(), None
        except ValueError:
            return None, f"{source} returned invalid JSON"

    def get_records(
        self,
        url,
        params=None,
        headers=None,
        *,
        source="Provider",
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Validate a record list before matching individual mints."""

        data, error = self.get_json(url, params, headers, source=source)
        if error:
            return [], error
        if not isinstance(data, list) or any(
            not isinstance(item, dict) for item in data
        ):
            return [], f"{source} returned an unexpected response shape"
        return data, None
