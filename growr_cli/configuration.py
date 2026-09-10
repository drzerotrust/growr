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
            f"Invalid {name}; configure an HTTP(S) URL in .env "
            "or adopt the default from .env.example"
        )


def _endpoint(name) -> None:
    """Log public defaults verbatim and conceal custom endpoints."""

    value = getattr(settings, name)
    _check_url(name, value)
    default = getattr(settings, f"DEFAULT_{name}").rstrip("/")
    display = (
        f"default {default}" if value == default else "configured (hidden)"
    )
    LOGGER.info("%s: %s", name, display)


def _key(name) -> bool:
    """Reject copied placeholders and log key presence only."""

    value = getattr(settings, name)
    if value in {"your_helius_api_key", "your_jupiter_api_key"}:
        raise ConfigurationError(
            f"Replace the placeholder in {name} or leave it blank in .env"
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

    env_exists = (settings.PROJECT_ROOT / ".env").is_file()
    origin = ".env loaded" if env_exists else "no .env file"
    LOGGER.info(
        "Configuration: %s; process environment takes precedence. "
        "Unset values use .env.example defaults.",
        origin,
    )
    _log_timeout()
    if args.scan_type != "list" or args.on_chain:
        _rpc_configuration(rpc_url, rpc_override)
    else:
        LOGGER.info("RPC: unused for this listing (enable with --on-chain)")

    if args.scan_type in {"wallet", "token-account"}:
        return
    if args.scan_type == "list":
        _endpoint("DEXSCREENER_V1_API_URL")
        if not args.stonk:
            return
        _endpoint("STONKS_API_URL")
        jupiter_enabled = True
    else:
        _endpoint("DEXSCREENER_API_URL")
        if not args.no_rugcheck:
            _endpoint("RUGCHECK_API_URL")
        jupiter_enabled = not args.no_jupiter
    if jupiter_enabled:
        if _key("JUPITER_API_KEY"):
            _endpoint("JUPITER_API_URL")
        else:
            LOGGER.info(
                "Jupiter enrichment requires JUPITER_API_KEY "
                "(or JUP_API_KEY); coverage will be not_configured"
            )
