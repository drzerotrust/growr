"""Tests for dotenv-backed module settings."""

from __future__ import annotations

import importlib

from growr_cli import settings

SETTING_ENVIRONMENT_VARIABLES = (
    "HELIUS_API_KEY",
    "JUPITER_API_KEY",
    "JUP_API_KEY",
    "SOLANA_RPC_URL",
    "CUSTOM_RPC_URL",
    "PUBLIC_SOLANA_RPC_URL",
    "HELIUS_MAINNET_RPC_URL",
    "REQUEST_TIMEOUT_SECONDS",
    "RUGCHECK_API_URL",
    "DEXSCREENER_API_URL",
    "DEXSCREENER_V1_API_URL",
    "STONKS_API_URL",
    "JUPITER_API_URL",
)


def _reload_settings(monkeypatch):
    """Reload settings with supported variables reset."""

    for name in SETTING_ENVIRONMENT_VARIABLES:
        monkeypatch.setenv(name, "")
    return importlib.reload(settings)


def test_helius_beats_custom_rpc(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("SOLANA_RPC_URL", "https://custom.example")
    monkeypatch.setenv("HELIUS_API_KEY", "secret-key")
    configured_settings = importlib.reload(configured_settings)

    assert (
        configured_settings.RPC_URL
        == "https://mainnet.helius-rpc.com?api-key=secret-key"
    )
    assert configured_settings.RPC_LABEL == "Helius RPC"


def test_custom_rpc_used_without_helius(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("SOLANA_RPC_URL", "https://custom.example")
    configured_settings = importlib.reload(configured_settings)

    assert configured_settings.RPC_URL == "https://custom.example"
    assert configured_settings.RPC_LABEL == "custom RPC"


def test_public_rpc_fallback(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)

    assert configured_settings.RPC_URL == "https://api.mainnet-beta.solana.com"
    assert configured_settings.RPC_LABEL == "public Solana RPC"


def test_invalid_and_non_positive_timeouts_fall_back(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "nope")
    configured_settings = importlib.reload(configured_settings)
    assert (
        configured_settings.REQUEST_TIMEOUT_SECONDS
        == configured_settings.DEFAULT_TIMEOUT_SECONDS
    )

    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "0")
    configured_settings = importlib.reload(configured_settings)
    assert (
        configured_settings.REQUEST_TIMEOUT_SECONDS
        == configured_settings.DEFAULT_TIMEOUT_SECONDS
    )

    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "20")
    configured_settings = importlib.reload(configured_settings)
    assert configured_settings.REQUEST_TIMEOUT_SECONDS == 20.0


def test_jupiter_key_alias(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("JUP_API_KEY", "jup-secret")
    configured_settings = importlib.reload(configured_settings)

    assert configured_settings.JUPITER_API_KEY == "jup-secret"


def test_process_environment_wins_over_dotenv(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("PUBLIC_SOLANA_RPC_URL", "https://process.example")
    configured_settings = importlib.reload(configured_settings)

    assert (
        configured_settings.PUBLIC_SOLANA_RPC_URL == "https://process.example"
    )


def test_provider_api_urls_are_environment_settings(monkeypatch) -> None:
    configured_settings = _reload_settings(monkeypatch)
    monkeypatch.setenv("RUGCHECK_API_URL", "https://rugcheck.example/")
    monkeypatch.setenv("DEXSCREENER_API_URL", "https://dexscreener.example/")
    monkeypatch.setenv("DEXSCREENER_V1_API_URL", "https://dex-v1.example/")
    monkeypatch.setenv("JUPITER_API_URL", "https://jupiter.example/")
    configured_settings = importlib.reload(configured_settings)

    assert configured_settings.RUGCHECK_API_URL == "https://rugcheck.example"
    assert (
        configured_settings.DEXSCREENER_API_URL
        == "https://dexscreener.example"
    )
    assert (
        configured_settings.DEXSCREENER_V1_API_URL == "https://dex-v1.example"
    )
    assert configured_settings.JUPITER_API_URL == "https://jupiter.example"
