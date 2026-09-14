"""Stonkfun v1 envelopes and token field translation."""

from typing import Any

from growr_cli import settings

ERROR_CODES = {
    "invalid_request",
    "forbidden",
    "not_found",
    "method_not_allowed",
    "conflict",
    "rate_limited",
    "internal",
    "service_unavailable",
}


def fetch(http, path, params=None) -> tuple[Any, str | None]:
    """Retain raw envelopes and expose only documented error codes."""

    envelope, error = http.get_json(
        "%s/%s" % (settings.STONKS_API_URL, path),
        params=params,
        source="Stonks",
        include_error_body=True,
    )
    code = error_code(envelope)
    if code in ERROR_CODES:
        detail = error or "Stonks returned an API error"
        return envelope, "%s (%s)" % (detail, code)
    if error:
        return envelope, error
    if not isinstance(envelope, dict) or not isinstance(
        envelope.get("data"), dict
    ):
        return envelope, "Stonks returned an unexpected response shape"
    return envelope, None


def error_code(envelope) -> str | None:
    """Read stable API codes without exposing error messages."""

    error = envelope.get("error") if isinstance(envelope, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def token_fields(token) -> dict[str, Any]:
    """Translate nested v1 fields into internal pool records."""

    # Only documented nested values supply market and social evidence.
    # Never promote provider-controlled analytics or flat lookalikes.
    fields = {
        name: token[name]
        for name in (
            "mint",
            "pool",
            "name",
            "symbol",
            "creator",
            "launchpad",
            "mode",
            "quoteOnlyFees",
            "imageUrl",
            "metadataUri",
            "status",
            "graduationProgress",
            "graduatedAt",
            "createdAt",
        )
        if name in token
    }
    for name in ("market", "quote", "links", "transferFee"):
        if token.get(name) is not None and not isinstance(token[name], dict):
            raise ValueError("Stonks returned an unexpected token shape")
    market = token.get("market") or {}
    fields.update(
        {
            name: market[name]
            for name in (
                "priceUsd",
                "marketCapUsd",
                "fdvUsd",
                "volume24hUsd",
                "priceChange24h",
                "peakMarketCapUsd",
            )
            if name in market
        }
    )
    quote = token.get("quote") or {}
    fields.update(
        {
            output: quote[name]
            for name, output in (
                ("mint", "quoteMint"),
                ("name", "quoteName"),
                ("symbol", "quoteSymbol"),
                ("category", "quoteCategory"),
            )
            if name in quote
        }
    )
    links = token.get("links") or {}
    fields.update(
        {
            name: links[name]
            for name in ("website", "twitter", "telegram")
            if name in links
        }
    )
    if token.get("mode") in ("standard", "reward"):
        fields["isRewardLaunch"] = token["mode"] == "reward"
    fee = token.get("transferFee") or {}
    if "bps" in fee:
        fields["transferTaxBps"] = fee["bps"]
    return fields
