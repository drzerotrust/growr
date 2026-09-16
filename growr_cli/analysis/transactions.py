"""Normalize transaction evidence without guessing swaps."""

from typing import Any

from growr_cli.analysis.transaction_balances import (
    account_keys,
    native_balances,
    token_balances,
)

SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAMS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}
SYSTEM_ACTIONS = {
    "transfer",
    "transferWithSeed",
    "createAccount",
    "createAccountWithSeed",
}
TOKEN_ACTIONS = {
    "transfer",
    "transferChecked",
    "mintTo",
    "mintToChecked",
    "burn",
    "burnChecked",
    "closeAccount",
    "initializeAccount",
    "initializeAccount2",
    "initializeAccount3",
    "syncNative",
}


def instruction_rows(message, meta, keys) -> list[dict[str, Any]]:
    """Retain outer/inner instruction positions and unknown programs."""

    groups = [(None, message.get("instructions", []))]
    groups.extend(
        (group["index"], group["instructions"])
        for group in meta.get("innerInstructions") or []
    )
    rows = []
    for parent, instructions in groups:
        for index, instruction in enumerate(instructions):
            program = instruction.get("programId")
            if program is None:
                program = keys[instruction["programIdIndex"]]
            parsed = instruction.get("parsed")
            parsed = parsed if isinstance(parsed, dict) else {}
            rows.append(
                {
                    "outer_index": index if parent is None else parent,
                    "inner_index": None if parent is None else index,
                    "stack_height": instruction.get("stackHeight"),
                    "program_id": program,
                    "type": parsed.get("type", "unknown"),
                    "info": parsed.get("info"),
                    "data": instruction.get("data"),
                    "accounts": instruction.get("accounts"),
                }
            )
    return rows


def completed_events(instructions, signature, slot) -> list[dict[str, Any]]:
    """Recognize System/token actions with source positions."""

    events = []
    for instruction in instructions:
        program = instruction["program_id"]
        actions = SYSTEM_ACTIONS if program == SYSTEM_PROGRAM else set()
        if program in TOKEN_PROGRAMS:
            actions = TOKEN_ACTIONS
        if instruction["type"] not in actions or not isinstance(
            instruction["info"], dict
        ):
            continue
        info = instruction["info"]
        amount = info.get("amount", info.get("lamports"))
        units = info.get("tokenAmount") or {}
        amount = units.get("amount", amount)
        events.append(
            {
                "source": "rpc",
                "signature": signature,
                "slot": slot,
                "outer_index": instruction["outer_index"],
                "inner_index": instruction["inner_index"],
                "program_id": program,
                "type": instruction["type"],
                "from": info.get("source"),
                "to": info.get("destination"),
                "account": info.get("account", info.get("newAccount")),
                "authority": info.get(
                    "authority", info.get("mintAuthority", info.get("owner"))
                ),
                "mint": info.get("mint"),
                "raw_amount": str(amount) if amount is not None else None,
                "decimals": 9
                if program == SYSTEM_PROGRAM
                else units.get("decimals"),
                "asset": "SOL" if program == SYSTEM_PROGRAM else "token",
            }
        )
    return events


def normalize_transaction(body, signature) -> dict[str, Any]:
    """Keep transaction outcome separate from instruction intentions."""

    transaction = body["transaction"]
    if (
        not transaction["signatures"]
        or transaction["signatures"][0] != signature
    ):
        raise ValueError("Transaction signature does not match request")
    if body.get("version", "legacy") not in ("legacy", 0):
        raise ValueError("Unsupported transaction version")
    message = transaction["message"]
    meta = body.get("meta")
    status = "unknown"
    if meta is not None:
        status = "failed" if meta["err"] is not None else "success"
    meta = meta or {}
    keys, signers = account_keys(message, meta)
    instructions = instruction_rows(message, meta, keys)
    logs = meta.get("logMessages")
    inner_execution_known = logs is not None and not any(
        line.startswith("Program ") and " failed:" in line for line in logs
    )
    # A caller can catch a failed CPI. With incomplete logs or caught
    # failures, inner instructions remain intentions, not proof of a
    # completed movement. Successful top-level standard actions remain.
    eligible = [
        item
        for item in instructions
        if item["inner_index"] is None or inner_execution_known
    ]
    events = (
        completed_events(eligible, signature, body["slot"])
        if status == "success"
        else []
    )
    return {
        "signature": signature,
        "slot": body["slot"],
        "block_time": body.get("blockTime"),
        "version": body.get("version"),
        "execution_status": status,
        "error": meta.get("err"),
        "fee_lamports": str(meta["fee"]) if "fee" in meta else None,
        "fee_payer": keys[0] if keys else None,
        "signers": signers,
        "account_keys": keys,
        "native_balances": native_balances(keys, meta),
        "token_balances": token_balances(keys, meta),
        "instructions": instructions,
        "events": events,
        "logs": meta.get("logMessages"),
        "recording": {
            "metadata": body.get("meta") is not None,
            "inner_execution": inner_execution_known,
            "inner_instructions": meta.get("innerInstructions") is not None,
            "token_balances": meta.get("preTokenBalances") is not None
            and meta.get("postTokenBalances") is not None,
        },
    }
