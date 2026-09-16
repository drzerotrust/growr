"""Shared binary fixtures for SPL layout tests."""

from __future__ import annotations

from solders.account import Account
from solders.rpc.responses import RpcKeyedAccount


def make_mint_bytes(
    *,
    initialized=True,
    has_mint_authority=True,
    has_freeze_authority=False,
    supply=1_000,
    decimals=6,
) -> bytes:
    """Build an 82-byte SPL mint account."""

    data = bytearray(82)
    if has_mint_authority:
        data[0:4] = (1).to_bytes(4, "little")
        data[4:36] = bytes(range(32))
    data[36:44] = supply.to_bytes(8, "little")
    data[44] = decimals
    data[45] = 1 if initialized else 0
    if has_freeze_authority:
        data[46:50] = (1).to_bytes(4, "little")
        data[50:82] = bytes(range(32, 64))
    return bytes(data)


def make_token_account_bytes(
    *,
    state=1,
    amount=50,
    has_delegate=False,
    has_close_authority=False,
) -> bytes:
    """Build a 165-byte SPL token account."""

    data = bytearray(165)
    data[0:32] = bytes(range(32))
    data[32:64] = bytes(range(32, 64))
    data[64:72] = amount.to_bytes(8, "little")
    if has_delegate:
        data[72:76] = (1).to_bytes(4, "little")
        data[76:108] = bytes(range(32))
    data[108] = state
    if has_close_authority:
        data[129:133] = (1).to_bytes(4, "little")
        data[133:165] = bytes(range(32, 64))
    return bytes(data)


def make_borsh_string(text) -> bytes:
    encoded = text.encode("utf-8")
    return len(encoded).to_bytes(4, "little") + encoded


def make_rpc_token_account(
    address, wallet, program, *, amount=50, state=1, extended=False
) -> RpcKeyedAccount:
    """Wrap token bytes in the SDK's wallet inventory shape."""

    data = bytearray(make_token_account_bytes(amount=amount, state=state))
    data[32:64] = bytes(wallet)
    if extended:
        # Token-2022 account tag followed by an ImmutableOwner TLV.
        data += b"\x02\x07\x00\x00\x00"
    return RpcKeyedAccount(address, Account(1, bytes(data), program))


def make_signature_record(index=1):
    """Build an SDK signature response without making a request."""

    from solders.rpc.responses import (
        RpcConfirmedTransactionStatusWithSignature,
    )
    from solders.signature import Signature
    from solders.transaction_status import TransactionConfirmationStatus

    return RpcConfirmedTransactionStatusWithSignature(
        Signature.from_bytes(bytes([index]) * 64),
        42,
        None,
        None,
        1700000000,
        TransactionConfirmationStatus.Finalized,
    )
