"""Validate active configuration and describe it without credentials."""

from math import isfinite
from urllib.parse import urlsplit

from growr_cli import settings
from growr_cli.logger import get_logger

LOGGER = get_logger(__name__)


class ConfigurationError(ValueError):
    """A safe, actionable error containing setting names only."""


def _check_url(name, value) -> None:
    """Reject unusable endpoints without including their contents."""

    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.hostname != "your-rpc.example.com"
            and not any(character.isspace() for character in value)
        )
        # Accessing port also checks malformed and out-of-range ports.
        valid = valid and (parsed.port is None or parsed.port > 0)
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(
            (
                "Invalid %s; configure an HTTP(S) URL in .env or adopt the "
                "default from .env.example"
            )
            % name
        )


def _endpoint(name) -> None:
    """Log public defaults verbatim and conceal custom endpoints."""

    value = getattr(settings, name)
    _check_url(name, value)
    default = getattr(settings, "DEFAULT_%s" % name).rstrip("/")
    display = (
        "default %s" % default if value == default else "configured (hidden)"
    )
    LOGGER.info("%s: %s", name, display)


def _key(name) -> bool:
    """Reject copied placeholders and log key presence only."""

    value = getattr(settings, name)
    if value in {"your_helius_api_key", "your_jupiter_api_key"}:
        raise ConfigurationError(
            "Replace the placeholder in %s or leave it blank in .env" % name
        )
    state = "configured (hidden)" if value else "unset"
    LOGGER.info("%s: %s", name, state)
    return bool(value)


def _rpc_configuration(rpc_url, rpc_override) -> None:
    """Describe the selected RPC without leaking endpoint secrets."""

    _check_url("RPC URL", rpc_url)
    if rpc_override:
        LOGGER.info("RPC: CLI override (hidden)")
    elif settings.HELIUS_API_KEY:
        _key("HELIUS_API_KEY")
        _endpoint("HELIUS_MAINNET_RPC_URL")
        LOGGER.info("RPC: Helius")
    elif settings.CUSTOM_RPC_URL:
        LOGGER.info("RPC: custom endpoint (hidden)")
    else:
        _endpoint("PUBLIC_SOLANA_RPC_URL")
        LOGGER.info("RPC: public Solana fallback; HELIUS_API_KEY is unset")


def _log_timeout() -> None:
    """Explain timeout fallback without echoing invalid input."""

    timeout = settings.REQUEST_TIMEOUT_SECONDS
    if not isfinite(timeout) or timeout <= 0:
        raise ConfigurationError(
            "REQUEST_TIMEOUT_SECONDS must be finite and positive"
        )
    raw = settings.REQUEST_TIMEOUT_VALUE
    if raw is not None:
        try:
            requested = float(raw)
            valid = isfinite(requested) and requested > 0
        except ValueError:
            valid = False
        if not valid:
            LOGGER.warning(
                "Invalid REQUEST_TIMEOUT_SECONDS; using default %s seconds",
                timeout,
            )
            return
    source = "default" if raw is None else "configured"
    LOGGER.info("REQUEST_TIMEOUT_SECONDS: %s %s seconds", source, timeout)


def log_configuration(args, rpc_url, rpc_override) -> None:
    """Check active settings before creating network clients."""

    environment = settings.ENVIRONMENT_FILE
    if environment["status"] == "invalid":
        raise ConfigurationError(
            "Unable to read environment file; check GROWR_ENV_FILE "
            "or the selected local .env"
        )
    origin = "%s configuration (%s)" % (
        environment["source"],
        environment["status"],
    )
    LOGGER.info(
        "Configuration: %s; process environment takes precedence. "
        "Unset values use .env.example defaults.",
        origin,
    )
    _log_timeout()
    if args.scan_type == "search":
        _search_configuration(args)
        return
    if args.scan_type != "list" or args.on_chain:
        _rpc_configuration(rpc_url, rpc_override)
    else:
        LOGGER.info("RPC: unused for this listing (enable with --on-chain)")

    if args.scan_type in {"wallet", "token-account", "history", "transaction"}:
        return
    if args.scan_type == "token" and args.stonk:
        _endpoint("STONKS_API_URL")
        _endpoint("STONKS_HOLDERS_API_URL")
        return
    if args.scan_type == "list":
        if args.stonk:
            _endpoint("STONKS_API_URL")
        jupiter_enabled = True
    else:
        if not args.no_rugcheck:
            _endpoint("RUGCHECK_API_URL")
        jupiter_enabled = not args.no_jupiter
    if jupiter_enabled:
        _jupiter_configuration(
            required=args.scan_type == "list" and not args.stonk
        )


def _search_configuration(args) -> None:
    """Validate only the provider selected for query discovery."""

    LOGGER.info("RPC: unused for token search")
    if args.provider == "stonks":
        _endpoint("STONKS_API_URL")
    else:
        _jupiter_configuration(required=True)


def _jupiter_configuration(required=False) -> None:
    """Require a discovery key; allow optional scan context."""

    if _key("JUPITER_API_KEY"):
        _endpoint("JUPITER_API_URL")
        return
    if required:
        raise ConfigurationError(
            "Jupiter discovery requires JUPITER_API_KEY in .env"
        )
    LOGGER.info(
        "Jupiter enrichment requires JUPITER_API_KEY "
        "(or JUP_API_KEY); coverage will be not_configured"
    )
