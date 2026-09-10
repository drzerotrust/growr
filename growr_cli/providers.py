"""Compatibility facade for callers of the original combined client."""

from __future__ import annotations

from typing import Any

from growr_cli.integrations.dexscreener import DexscreenerClient
from growr_cli.integrations.http import HttpClient
from growr_cli.integrations.jupiter import JupiterClient
from growr_cli.integrations.rugcheck import RugcheckClient
from growr_cli.models import EnrichmentResult


class ProviderClient:
    """Delegate legacy calls to provider-owned integrations."""

    def __init__(self, timeout_seconds, jupiter_api_key) -> None:
        """Retain one shared session for existing library callers."""

        self.http = HttpClient(timeout_seconds)
        self.session = self.http.session
        self.jupiter = JupiterClient(self.http, jupiter_api_key)
        self.dexscreener = DexscreenerClient(self.http)
        self.rugcheck = RugcheckClient(self.http)

    def close(self) -> None:
        """Close the transport owned by this compatibility client."""

        self.http.close()

    def get_jupiter_token(
        self, mint
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Retain the legacy Jupiter tuple contract."""

        return self.jupiter._get_single(mint)

    def get_dexscreener_pairs(
        self, mint
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Retain the legacy Dexscreener tuple contract."""

        return self.dexscreener._get_single(mint)

    def get_rugcheck_report(
        self, mint
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Retain the legacy Rugcheck tuple contract."""

        return self.rugcheck._get_single(mint)

    def get_jupiter_tokens(self, mints) -> dict[str, EnrichmentResult]:
        """Delegate exact-mint batch lookup to Jupiter."""

        return self.jupiter.get_tokens(mints)

    def get_dexscreener_tokens(self, mints) -> dict[str, EnrichmentResult]:
        """Delegate exact base-mint lookup to Dexscreener."""

        return self.dexscreener.get_tokens(mints)
