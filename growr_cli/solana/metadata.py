"""Read and interpret Solana metadata data."""

from typing import Any

from solders.pubkey import Pubkey

from growr_cli.solana.decoding import read_rust_string
from growr_cli.solana.rpc import METADATA_PROGRAM_ID


def read_metadata(rpc, mint) -> dict[str, Any]:
    """Read standard Metaplex metadata when available."""

    metadata_address = rpc.find_metadata_address(mint)
    data, owner = rpc.get_account_data(metadata_address)
    result = {
        "exists": False,
        "address": str(metadata_address),
        "source": "none",
    }

    if data is None:
        return result
    if owner != str(METADATA_PROGRAM_ID):
        result["warning"] = "Derived metadata account has an unexpected owner"
        return result
    if len(data) < 65 or data[0] != 4:
        result["warning"] = "Metadata account has an unexpected layout"
        return result

    offset = 1
    update_authority = str(Pubkey.from_bytes(data[offset : offset + 32]))
    offset += 64
    name, offset, name_truncated = read_rust_string(data, offset)
    symbol, offset, symbol_truncated = read_rust_string(data, offset)
    uri, _offset, uri_truncated = read_rust_string(data, offset)
    metadata = {
        "exists": True,
        "address": str(metadata_address),
        "source": "metaplex",
        "update_authority": update_authority,
        "name": name,
        "symbol": symbol,
        "uri": uri,
    }
    if name_truncated or symbol_truncated or uri_truncated:
        metadata["warning"] = "Metadata strings were truncated or corrupt"
    return metadata
