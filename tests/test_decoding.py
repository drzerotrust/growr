from solders.pubkey import Pubkey

from growr_cli.decoding import (
    parse_mint,
    parse_optional_pubkey,
    parse_token_account,
    read_rust_string,
    require_token_program_owner,
    token_program_name,
)
from growr_cli.solana_rpc import SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID
from tests.conftest import (
    make_borsh_string,
    make_mint_bytes,
    make_token_account_bytes,
)


def test_token_2022_program_id_is_official() -> None:
    assert (
        str(TOKEN_2022_PROGRAM_ID)
        == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    )


def test_require_token_program_owner_accepts_spl_and_token_2022() -> None:
    require_token_program_owner(str(SPL_TOKEN_PROGRAM_ID), "mint")
    require_token_program_owner(str(TOKEN_2022_PROGRAM_ID), "token account")


def test_require_token_program_owner_rejects_other_programs() -> None:
    try:
        require_token_program_owner("11111111111111111111111111111111", "mint")
    except ValueError as error:
        assert "not an SPL mint" in str(error)
        assert "11111111111111111111111111111111" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_parse_optional_pubkey_none_and_present() -> None:
    empty = bytes(36)
    assert parse_optional_pubkey(empty, 0) is None

    present = bytearray(36)
    present[0:4] = (1).to_bytes(4, "little")
    present[4:36] = bytes(range(32))
    assert parse_optional_pubkey(bytes(present), 0) == str(
        Pubkey.from_bytes(bytes(range(32)))
    )


def test_parse_optional_pubkey_short_buffer() -> None:
    assert parse_optional_pubkey(b"\x01\x00", 0) is None


def test_parse_mint_initialized_with_authorities() -> None:
    data = make_mint_bytes(
        has_mint_authority=True,
        has_freeze_authority=True,
        supply=2500,
        decimals=9,
    )
    parsed = parse_mint(data, str(SPL_TOKEN_PROGRAM_ID))

    assert parsed["token_program"] == "spl_token"
    assert parsed["initialized"] is True
    assert parsed["supply"] == "2500"
    assert parsed["decimals"] == 9
    assert parsed["mint_authority"] == str(Pubkey.from_bytes(bytes(range(32))))
    assert parsed["freeze_authority"] == str(
        Pubkey.from_bytes(bytes(range(32, 64)))
    )


def test_parse_mint_uninitialized() -> None:
    data = make_mint_bytes(initialized=False, has_mint_authority=True)
    parsed = parse_mint(data, str(TOKEN_2022_PROGRAM_ID))
    assert parsed["initialized"] is False
    assert parsed["token_program"] == "token_2022"


def test_parse_mint_rejects_short_buffer() -> None:
    try:
        parse_mint(b"\x00" * 10, str(SPL_TOKEN_PROGRAM_ID))
    except ValueError as error:
        assert "expected at least 82 bytes, got 10" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_parse_token_account_states_and_authorities() -> None:
    data = make_token_account_bytes(
        state=2, amount=77, has_delegate=True, has_close_authority=True
    )
    parsed = parse_token_account(data, str(SPL_TOKEN_PROGRAM_ID))

    assert parsed["state"] == "frozen"
    assert parsed["raw_amount"] == "77"
    assert parsed["delegate"] == str(Pubkey.from_bytes(bytes(range(32))))
    assert parsed["close_authority"] == str(
        Pubkey.from_bytes(bytes(range(32, 64)))
    )
    assert parsed["mint"] == str(Pubkey.from_bytes(bytes(range(32))))
    assert parsed["owner"] == str(Pubkey.from_bytes(bytes(range(32, 64))))


def test_token_program_name_unknown() -> None:
    assert (
        token_program_name("So11111111111111111111111111111111111111112")
        == "unknown"
    )


def test_read_rust_string_complete() -> None:
    payload = make_borsh_string("BONK")
    text, offset, truncated = read_rust_string(payload, 0)
    assert text == "BONK"
    assert offset == len(payload)
    assert truncated is False


def test_read_rust_string_truncated() -> None:
    payload = (8).to_bytes(4, "little") + b"abc"
    text, offset, truncated = read_rust_string(payload, 0)
    assert text == "abc"
    assert offset == len(payload)
    assert truncated is True


def test_read_rust_string_missing_length() -> None:
    text, offset, truncated = read_rust_string(b"\x01", 0)
    assert text == ""
    assert offset == 1
    assert truncated is True
