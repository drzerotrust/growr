"""TokenAccountScanner workflow and report assembly."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from growr_cli.logger import get_logger
from growr_cli.models import (
    Finding,
    ScanReport,
)
from growr_cli.scanners.base import BaseScanner
from growr_cli.solana.decoding import parse_token_account

LOGGER = get_logger(__name__)


class TokenAccountScanner(BaseScanner):
    """Read an SPL Token or Token-2022 account and owner context."""

    def __init__(self, rpc, rpc_label) -> None:
        """Create a token-account scanner.

        Args:
            rpc: Read-only Solana RPC client.
            rpc_label: Secret-free RPC label for the report.
        """

        super().__init__(rpc, rpc_label)

    def scan(self, token_account_text) -> ScanReport:
        """Scan one SPL Token or Token-2022 holding account.

        Args:
            token_account_text: Token-account address.

        Returns:
            A completed token-account scan report.

        Raises:
            ValueError: If the address is invalid, missing, or not a
                token account.
        """

        token_account = self.rpc.parse_address(token_account_text)
        report = self.new_report("token_account", token_account_text)
        LOGGER.info("Reading and validating the token account")
        data, owner_program = self.rpc.get_account_data(token_account)
        if data is None or owner_program is None:
            raise ValueError(
                "Token account was not found on the configured RPC"
            )
        account = parse_token_account(data, owner_program)
        report.summary["token_account"] = account
        report.findings.append(
            Finding(
                "high" if account["state"] == "frozen" else "info",
                "Token account state",
                (
                    "Account is %s and holds %s raw token units."
                    % (account["state"], account["raw_amount"])
                ),
                "on-chain RPC",
            )
        )

        if account["delegate"]:
            report.findings.append(
                Finding(
                    "medium",
                    "Delegate present",
                    "A delegate is configured for this token account.",
                    "on-chain RPC",
                )
            )
        if account["close_authority"]:
            report.findings.append(
                Finding(
                    "low",
                    "Close authority present",
                    "A close authority is configured for this token account.",
                    "on-chain RPC",
                )
            )

        owner = self.rpc.parse_address(account["owner"])
        LOGGER.info("Reading owner-wallet balance and recent activity")
        with ThreadPoolExecutor(max_workers=2) as pool:
            balance_future = pool.submit(self.rpc.get_balance_sol, owner)
            signatures_future = pool.submit(self.rpc.get_signatures, owner, 10)
            sol_balance = balance_future.result()
            signatures = signatures_future.result()

        report.summary["owner_wallet"] = {
            "address": account["owner"],
            "sol_balance": sol_balance,
            "recent_signature_count": len(signatures),
        }
        return report
