"""Application settings loaded from the repository environment."""

from __future__ import annotations

import os
from math import isfinite
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_PUBLIC_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
DEFAULT_HELIUS_MAINNET_RPC_URL = "https://mainnet.helius-rpc.com"
DEFAULT_RUGCHECK_API_URL = "https://api.rugcheck.xyz/v1"
DEFAULT_JUPITER_API_URL = "https://api.jup.ag/tokens/v2"
DEFAULT_STONKS_API_URL = "https://www.stonkfun.xyz/api/public/v1"
DEFAULT_STONKS_HOLDERS_API_URL = "https://www.stonkfun.xyz/api/token-holders"


def _environment_value(*names) -> str | None:
    """Return the first non-blank environment value from ``names``."""

    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _timeout_seconds(value) -> float:
    """Parse a positive timeout or return the application default."""

    if value is None:
        return DEFAULT_TIMEOUT_SECONDS

    try:
        timeout = float(value)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS

    return (
        timeout
        if isfinite(timeout) and timeout > 0
        else DEFAULT_TIMEOUT_SECONDS
    )


def _base_url(value, default) -> str:
    """Return a URL base without a trailing slash."""

    return (value or default).rstrip("/")


load_dotenv(PROJECT_ROOT / ".env", override=False)

PUBLIC_SOLANA_RPC_URL = (
    _environment_value("PUBLIC_SOLANA_RPC_URL")
    or DEFAULT_PUBLIC_SOLANA_RPC_URL
)
HELIUS_MAINNET_RPC_URL = (
    _environment_value("HELIUS_MAINNET_RPC_URL")
    or DEFAULT_HELIUS_MAINNET_RPC_URL
)
HELIUS_API_KEY = _environment_value("HELIUS_API_KEY")
JUPITER_API_KEY = _environment_value("JUPITER_API_KEY", "JUP_API_KEY")
CUSTOM_RPC_URL = _environment_value("SOLANA_RPC_URL", "CUSTOM_RPC_URL")
REQUEST_TIMEOUT_VALUE = _environment_value("REQUEST_TIMEOUT_SECONDS")
REQUEST_TIMEOUT_SECONDS = _timeout_seconds(REQUEST_TIMEOUT_VALUE)
RUGCHECK_API_URL = _base_url(
    _environment_value("RUGCHECK_API_URL"), DEFAULT_RUGCHECK_API_URL
)
JUPITER_API_URL = _base_url(
    _environment_value("JUPITER_API_URL"), DEFAULT_JUPITER_API_URL
)
STONKS_API_URL = _base_url(
    _environment_value("STONKS_API_URL"), DEFAULT_STONKS_API_URL
)
# Upgrade the previous public default; preserve custom endpoints.
if STONKS_API_URL == "https://www.stonkfun.xyz/api":
    STONKS_API_URL = DEFAULT_STONKS_API_URL
STONKS_HOLDERS_API_URL = _base_url(
    _environment_value("STONKS_HOLDERS_API_URL"),
    DEFAULT_STONKS_HOLDERS_API_URL,
)

if HELIUS_API_KEY:
    RPC_URL = "%s?api-key=%s" % (HELIUS_MAINNET_RPC_URL, HELIUS_API_KEY)
    RPC_LABEL = "Helius RPC"
elif CUSTOM_RPC_URL:
    RPC_URL = CUSTOM_RPC_URL
    RPC_LABEL = "custom RPC"
else:
    RPC_URL = PUBLIC_SOLANA_RPC_URL
    RPC_LABEL = "public Solana RPC"
