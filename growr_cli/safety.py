"""Prevent configured credentials from entering reports and logs."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import quote

from growr_cli import settings

_CREDENTIAL_QUERY = re.compile(
    r"((?:api[-_]?key|access_token|token|secret|password)=)[^&\s]+",
    re.IGNORECASE,
)

_PRIVATE_ENDPOINT = ContextVar("growr_private_endpoint", default="")


@contextmanager
def redact_endpoint(endpoint) -> Iterator[None]:
    """Keep endpoints private for this run, then restore state."""

    token = _PRIVATE_ENDPOINT.set(endpoint)
    try:
        yield
    finally:
        _PRIVATE_ENDPOINT.reset(token)


def safe_text(value) -> str:
    """Redact configured secrets and credential query parameters."""

    public_rpc = settings.DEFAULT_PUBLIC_SOLANA_RPC_URL
    endpoint = _PRIVATE_ENDPOINT.get()
    secrets = [endpoint] if endpoint != public_rpc else []
    for name in (
        "RPC_URL",
        "CUSTOM_RPC_URL",
        "HELIUS_MAINNET_RPC_URL",
        "JUPITER_API_URL",
        "STONKS_API_URL",
        "RUGCHECK_API_URL",
        "DEXSCREENER_API_URL",
        "DEXSCREENER_V1_API_URL",
    ):
        configured = getattr(settings, name, None)
        default = getattr(settings, f"DEFAULT_{name}", public_rpc).rstrip("/")
        if configured and configured.rstrip("/") != default:
            secrets.append(configured)
    secrets.extend(
        key
        for key in (settings.HELIUS_API_KEY, settings.JUPITER_API_KEY)
        if key
    )
    # Hide whole endpoints before replacing keys inside them. Also
    # account for URL-encoded echoes without recording raw credentials.
    variants = {
        variant
        for secret in secrets
        if secret
        for variant in (secret, quote(secret, safe=""))
    }
    result = str(value)
    for secret in sorted(variants, key=len, reverse=True):
        result = result.replace(secret, "REDACTED")
    return _CREDENTIAL_QUERY.sub(r"\1REDACTED", result)
