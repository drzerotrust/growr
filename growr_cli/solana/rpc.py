"""Read-only Solana RPC helpers built on solana-py and solders."""

from __future__ import annotations

import base64
from http import HTTPStatus
from typing import Any

import httpx
from solana.rpc.api import Client
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey

SPL_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)
TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)
METADATA_PROGRAM_ID = Pubkey.from_string(
    "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
)
LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_RPC_TIMEOUT_SECONDS = 15.0
RPC_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_RPC_HEADERS = {
    "Accept": "application/json",
    "User-Agent": RPC_USER_AGENT,
}


class RpcError(Exception):
    """An RPC failure with an operator-facing explanation."""


def format_rpc_error(error, method) -> str:
    """Turn a solana-py/httpx failure into a status-bearing message.

    Args:
        error: Exception raised by an RPC helper.
        method: JSON-RPC method name, such as
            ``getTokenLargestAccounts``.

    Returns:
        A single-line error that includes HTTP status when available and
        never echoes API keys from request URLs.
    """

    cause = _root_cause(error)
    details = _http_error_details(cause) or type(cause).__name__
    return "%s failed via RPC (%s)" % (method, details)


def _root_cause(error) -> BaseException:
    cause = error
    seen = set()
    while cause.__cause__ is not None and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.__cause__
    return cause


def _http_error_details(error) -> str | None:
    """Use known categories; response bodies can contain credentials."""

    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        # Use the standard phrase, never an untrusted server phrase.
        try:
            reason = HTTPStatus(code).phrase
        except ValueError:
            reason = "Unknown status"
        return "HTTP %s %s" % (code, reason)
    if isinstance(error, httpx.ConnectError):
        return "connection error"
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    return None


class SolanaRpcClient:
    """Read-only mainnet calls through the official Python client.

    Attributes:
        rpc_url: Endpoint passed to solana-py. Do not print this value;
            it may contain a provider API key in the query string.
        client: Underlying solana-py RPC client.
    """

    def __init__(
        self,
        rpc_url,
        timeout_seconds=DEFAULT_RPC_TIMEOUT_SECONDS,
    ) -> None:
        """Create a read-only RPC client.

        Args:
            rpc_url: Solana JSON-RPC endpoint.
            timeout_seconds: HTTP timeout applied to RPC requests.
                Public RPCs often inspect ``User-Agent``; a browser-like
                value is sent so default httpx/python agents are less
                likely to be dropped.
        """

        self.rpc_url = rpc_url
        self.extra_headers = dict(DEFAULT_RPC_HEADERS)
        self.client = Client(
            rpc_url, timeout=timeout_seconds, extra_headers=self.extra_headers
        )

    def close(self) -> None:
        """Release the HTTP connection pool owned by this RPC client."""

        self.client._provider.session.close()

    def _rpc(self, method, operation) -> Any:
        try:
            return operation()
        except RpcError:
            raise
        except Exception as error:
            raise RpcError(format_rpc_error(error, method)) from error

    def parse_address(self, address) -> Pubkey:
        """Validate a public key before it reaches an RPC endpoint.

        Args:
            address: Base58 address supplied by the user.

        Returns:
            A parsed ``Pubkey``.

        Raises:
            ValueError: If the address is not a valid public key.
        """

        return Pubkey.from_string(address)

    def get_account_data(self, address) -> tuple[bytes | None, str | None]:
        """Return raw account bytes and its owning program address.

        Args:
            address: Account to fetch.

        Returns:
            ``(data, owner)`` when the account exists, otherwise
            ``(None, None)``.
        """

        response = self._rpc(
            "getAccountInfo",
            lambda: self.client.get_account_info(address, encoding="base64"),
        )
        value = response.value
        if value is None:
            return None, None

        data = self.extract_bytes(value.data)
        return data, str(value.owner)

    def get_balance_sol(self, address) -> float:
        """Read a wallet's native SOL balance.

        Args:
            address: Wallet address.

        Returns:
            Balance in SOL, not lamports.
        """

        response = self._rpc(
            "getBalance", lambda: self.client.get_balance(address)
        )
        return response.value / LAMPORTS_PER_SOL

    def get_signatures(self, address, limit) -> list[Any]:
        """Read recent transaction signatures.

        Args:
            address: Account whose signatures should be listed.
            limit: Maximum number of signatures to return.

        Returns:
            Recent signature records from the RPC.
        """

        response = self._rpc(
            "getSignaturesForAddress",
            lambda: self.client.get_signatures_for_address(
                address, limit=limit
            ),
        )
        return list(response.value)

    def get_largest_token_accounts(self, mint) -> list[Any]:
        """Return the largest token accounts for a mint.

        Args:
            mint: Token mint to inspect.

        Returns:
            Largest token-account records from the RPC.
        """

        response = self._rpc(
            "getTokenLargestAccounts",
            lambda: self.client.get_token_largest_accounts(mint),
        )
        return list(response.value)

    def get_multiple_accounts(self, addresses) -> list[Any]:
        """Fetch multiple accounts in one RPC call.

        Args:
            addresses: Accounts to fetch.

        Returns:
            Account infos in the same order as ``addresses``.
        """

        if not addresses:
            return []
        response = self._rpc(
            "getMultipleAccounts",
            lambda: self.client.get_multiple_accounts(
                addresses, encoding="base64"
            ),
        )
        return list(response.value)

    def get_token_accounts_by_owner(self, wallet, program_id) -> list[Any]:
        """List wallet token accounts for a single token program.

        Args:
            wallet: Wallet that owns the token accounts.
            program_id: SPL Token or Token-2022 program ID.

        Returns:
            Token accounts returned by the RPC for that program.
        """

        options = TokenAccountOpts(program_id=program_id, encoding="base64")
        response = self._rpc(
            "getTokenAccountsByOwner",
            lambda: self.client.get_token_accounts_by_owner(wallet, options),
        )
        return list(response.value)

    def find_metadata_address(self, mint) -> Pubkey:
        """Derive the standard Metaplex metadata PDA for a mint.

        Args:
            mint: Token mint whose metadata PDA should be derived.

        Returns:
            Derived metadata account address.
        """

        seeds = [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint)]
        metadata_address, _bump = Pubkey.find_program_address(
            seeds, METADATA_PROGRAM_ID
        )
        return metadata_address

    def extract_bytes(self, data) -> bytes:
        """Extract bytes from supported solana-py response shapes.

        Args:
            data: Account data field from an RPC response.

        Returns:
            Raw account bytes.

        Raises:
            ValueError: If the RPC returned an empty or unsupported data
                shape.
        """

        if isinstance(data, bytes):
            return data

        if isinstance(data, (tuple, list)):
            if not data:
                raise ValueError("RPC returned empty account data")
            encoded = data[0]
            if isinstance(encoded, str):
                return base64.b64decode(encoded)

        if isinstance(data, str):
            return base64.b64decode(data)

        raise ValueError("RPC returned account data in an unsupported format")
