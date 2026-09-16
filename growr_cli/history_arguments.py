"""CLI definitions and local validation for bounded history commands."""

import argparse

from solders.signature import Signature


def bounded_count(value) -> int:
    """Accept a history page of one to one hundred signatures."""

    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return number


def signature_argument(value) -> str:
    """Reject invalid signatures before constructing network clients."""

    try:
        return str(Signature.from_string(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Invalid transaction signature"
        ) from error


def add_history_parsers(subparsers) -> None:
    """Keep history-specific help out of the main composition code."""

    transaction = subparsers.add_parser(
        "transaction",
        help="Inspect one transaction signature.",
        description="Read a legacy/v0 transaction, balances and System/token "
        "actions. Unknown programs remain uninterpreted. One RPC attempt.",
        epilog="Example: python3 growr.py --json transaction <SIGNATURE>",
    )
    transaction.add_argument(
        "signature",
        type=signature_argument,
        help="Transaction signature, not an address.",
    )
    transaction.help_on_error = True
    history = subparsers.add_parser(
        "history",
        help="Read one page of address activity.",
        description="Read signatures referencing a wallet or token-account "
        "address. --details adds one transaction read per distinct signature. "
        "This is not a complete wallet or mint transaction history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
        "  python3 growr.py --json history <ADDRESS> --limit 10\n"
        "  python3 growr.py history <ADDRESS> --details\n"
        "  python3 growr.py --json history <ADDRESS> --before <SIGNATURE>\n"
        "Global --commitment and --max-rpc-calls go before history.",
    )
    history.add_argument("address", help="Wallet or token-account address.")
    history.help_on_error = True
    history.add_argument(
        "--limit",
        type=bounded_count,
        default=20,
        help="Signatures per page, 1–100 (default: 20).",
    )
    history.add_argument(
        "--before",
        type=signature_argument,
        help="Continue before this signature (exclusive).",
    )
    history.add_argument(
        "--until",
        type=signature_argument,
        help="Stop at this signature (exclusive).",
    )
    history.add_argument(
        "--details",
        action="store_true",
        help="Fetch bodies; at most 1 + limit RPC attempts.",
    )
