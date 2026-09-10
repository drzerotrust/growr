import base64

import httpx
import pytest

from growr_cli.solana_rpc import (
    DEFAULT_RPC_HEADERS,
    RPC_USER_AGENT,
    RpcError,
    SolanaRpcClient,
    format_rpc_error,
)


def test_extract_bytes_from_supported_shapes() -> None:
    client = SolanaRpcClient("https://example.invalid", timeout_seconds=1)
    raw = b"hello"

    assert client.extract_bytes(raw) == raw
    assert client.extract_bytes(base64.b64encode(raw).decode("ascii")) == raw
    assert (
        client.extract_bytes((base64.b64encode(raw).decode("ascii"), "base64"))
        == raw
    )


def test_extract_bytes_rejects_empty_and_unknown() -> None:
    client = SolanaRpcClient("https://example.invalid", timeout_seconds=1)

    with pytest.raises(ValueError, match="empty account data"):
        client.extract_bytes([])

    with pytest.raises(ValueError, match="unsupported format"):
        client.extract_bytes(123)


def test_rpc_client_sets_browser_user_agent() -> None:
    client = SolanaRpcClient("https://example.invalid", timeout_seconds=1)

    assert client.extra_headers["User-Agent"] == RPC_USER_AGENT
    assert "Mozilla/5.0" in client.extra_headers["User-Agent"]
    assert client.extra_headers == DEFAULT_RPC_HEADERS


def test_format_rpc_error_keeps_status_without_response_body() -> None:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(429, request=request, text="Too many requests")
    cause = httpx.HTTPStatusError(
        "blocked", request=request, response=response
    )
    wrapped = Exception(
        "<class 'httpx.HTTPStatusError'> raised in GetTokenLargestAccounts"
    )
    wrapped.__cause__ = cause

    message = format_rpc_error(wrapped, "getTokenLargestAccounts")

    assert (
        message == "getTokenLargestAccounts failed via RPC (HTTP 429 Too Many "
        "Requests)"
    )


def test_format_rpc_error_redacts_api_key() -> None:
    request = httpx.Request(
        "POST", "https://mainnet.helius-rpc.com/?api-key=super-secret"
    )
    response = httpx.Response(
        403, request=request, text="forbidden api-key=super-secret"
    )
    cause = httpx.HTTPStatusError(
        "blocked", request=request, response=response
    )

    message = format_rpc_error(cause, "getAccountInfo")

    assert "super-secret" not in message
    assert "api-key=" not in message
    assert "HTTP 403" in message


def test_format_rpc_error_connection_failure() -> None:
    request = httpx.Request("POST", "https://example.invalid")
    cause = httpx.ConnectError("Name or service not known", request=request)

    message = format_rpc_error(cause, "getAccountInfo")

    assert message == "getAccountInfo failed via RPC (connection error)"
    assert "Name or service not known" not in message


def test_rpc_wrapper_raises_rpc_error(monkeypatch) -> None:
    client = SolanaRpcClient("https://example.invalid", timeout_seconds=1)

    def boom(_mint) -> None:
        request = httpx.Request("POST", "https://example.invalid")
        response = httpx.Response(403, request=request, text="blocked")
        raise httpx.HTTPStatusError(
            "blocked", request=request, response=response
        )

    monkeypatch.setattr(client.client, "get_token_largest_accounts", boom)

    with pytest.raises(
        RpcError, match="getTokenLargestAccounts failed via RPC \\(HTTP 403"
    ):
        client.get_largest_token_accounts(
            client.parse_address("11111111111111111111111111111111")
        )
