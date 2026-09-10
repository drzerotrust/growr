"""Binary layout decoders for SPL mint and token-account data.

These functions only interpret bytes. They do not talk to RPC or
providers.
"""

from __future__ import annotations

from typing import Any

from solders.pubkey import Pubkey

from growr_cli.solana.rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID

TOKEN_PROGRAM_OWNERS = frozenset(
    {
        str(SPL_TOKEN_PROGRAM_ID),
        str(TOKEN_2022_PROGRAM_ID),
    }
)


def require_token_program_owner(owner, account_kind) -> None:
    """Reject accounts that are not owned by an SPL token program.

    Args:
        owner: Program ID that owns the on-chain account.
        account_kind: Human-readable account type used in the error,
            such as ``mint`` or ``token account``.

    Raises:
        ValueError: If the owner is not SPL Token or Token-2022.
    """

    if owner not in TOKEN_PROGRAM_OWNERS:
        raise ValueError(
            f"Account is not an SPL {account_kind} (owner={owner})"
        )


def token_program_name(owner) -> str:
    """Map a token program owner to a stable summary label.

    Args:
        owner: Program ID that owns the account.

    Returns:
        ``spl_token``, ``token_2022``, or ``unknown``.
    """

    if owner == str(SPL_TOKEN_PROGRAM_ID):
        return "spl_token"
    if owner == str(TOKEN_2022_PROGRAM_ID):
        return "token_2022"
    return "unknown"


def parse_optional_pubkey(data, offset) -> str | None:
    """Parse Solana's COption<Pubkey> layout from a raw account buffer.

    Args:
        data: Raw account bytes.
        offset: Byte offset of the COption tag.

    Returns:
        Base58 public key when the option is present, otherwise
        ``None``.
    """

    if len(data) < offset + 36:
        return None

    # COption stores a four-byte tag followed by a 32-byte public key.
    option = int.from_bytes(data[offset : offset + 4], "little")
    if option == 0:
        return None
    if option != 1:
        raise ValueError("Invalid SPL public-key option tag")
    return str(Pubkey.from_bytes(data[offset + 4 : offset + 36]))


def _validate_layout(data, owner, kind, base_size, account_type) -> None:
    """Distinguish base layouts, extended layouts, and multisigs."""

    require_token_program_owner(owner, kind)
    size = len(data)
    if size == base_size:
        return
    if owner == str(SPL_TOKEN_PROGRAM_ID):
        raise ValueError(f"Invalid SPL {kind} account size")
    # Token-2022 keeps base accounts valid. Extended accounts share a
    # discriminator at byte 165; 355 bytes is reserved for multisigs.
    if size < 166 or size == 355 or data[165] != account_type:
        raise ValueError(f"Invalid Token-2022 {kind} account type")
    if base_size == 82 and any(data[82:165]):
        raise ValueError("Invalid Token-2022 mint padding")


def parse_mint(data, owner) -> dict[str, Any]:
    """Decode the common 82-byte SPL mint base layout.

    Args:
        data: Raw mint account bytes.
        owner: Program ID that owns the mint account.

    Returns:
        Decoded mint fields used by the token scanner.

    Raises:
        ValueError: If ownership, layout, or flags are invalid.
    """

    if len(data) < 82:
        raise ValueError(
            "Mint account is shorter than the SPL Token mint layout"
        )
    _validate_layout(data, owner, "mint", 82, 1)
    if data[45] not in (0, 1):
        raise ValueError("Invalid SPL mint initialization flag")

    # Decode the shared base layout; Token-2022 extensions follow it.
    supply = int.from_bytes(data[36:44], "little")
    decimals = data[44]
    return {
        "token_program": token_program_name(owner),
        "program_id": owner,
        "supply": str(supply),
        "decimals": decimals,
        "initialized": data[45] == 1,
        "mint_authority": parse_optional_pubkey(data, 0),
        "freeze_authority": parse_optional_pubkey(data, 46),
        "raw_account_bytes": len(data),
    }


def parse_token_account(data, owner_program) -> dict[str, Any]:
    """Decode the 165-byte base SPL token-account layout.

    Args:
        data: Raw token-account bytes.
        owner_program: Program ID that owns the token account.

    Returns:
        Decoded token-account fields used by the token-account scanner.

    Raises:
        ValueError: If ownership, layout, or flags are invalid.
    """

    if len(data) < 165:
        raise ValueError("Account is too short to be an SPL token account")
    _validate_layout(data, owner_program, "token account", 165, 2)
    if int.from_bytes(data[109:113], "little") not in (0, 1):
        raise ValueError("Invalid SPL native-balance option tag")

    state_value = data[108]
    states = {0: "uninitialized", 1: "initialized", 2: "frozen"}
    if state_value not in states:
        raise ValueError("Invalid SPL token-account state")
    state = states[state_value]

    return {
        "token_program": token_program_name(owner_program),
        "mint": str(Pubkey.from_bytes(data[0:32])),
        "owner": str(Pubkey.from_bytes(data[32:64])),
        "raw_amount": str(int.from_bytes(data[64:72], "little")),
        "delegate": parse_optional_pubkey(data, 72),
        "state": state,
        "close_authority": parse_optional_pubkey(data, 129),
    }


def read_rust_string(data, offset) -> tuple[str, int, bool]:
    """Decode a bounded Borsh string.

    Args:
        data: Raw account bytes.
        offset: Byte offset of the u32 length prefix.

    Returns:
        A tuple of ``(text, next_offset, truncated)``. ``truncated`` is
        True when the declared length runs past the end of the buffer.
    """

    if offset + 4 > len(data):
        return "", len(data), True
    # Bound the declared length before decoding untrusted data.
    length = int.from_bytes(data[offset : offset + 4], "little")
    start = offset + 4
    truncated = start + length > len(data)
    end = min(start + length, len(data))
    text = (
        data[start:end]
        .decode("utf-8", errors="replace")
        .rstrip("\x00")
        .strip()
    )
    return text, end, truncated
