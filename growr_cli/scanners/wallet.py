"""WalletScanner workflow and report assembly."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from growr_cli.logger import get_logger
from growr_cli.models import (
    Finding,
    ScanReport,
)
from growr_cli.scanners.base import BaseScanner
from growr_cli.solana.rpc import (
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
)

LOGGER = get_logger(__name__)


class WalletScanner(BaseScanner):
    """Scan wallet balance, activity, and token-account inventory."""

    def __init__(self, rpc, rpc_label) -> None:
        """Create a wallet scanner.

        Args:
            rpc: Read-only Solana RPC client.
            rpc_label: Secret-free RPC label for the report.
        """

        super().__init__(rpc, rpc_label)

    def scan(self, wallet_text) -> ScanReport:
        """Scan wallet balance, activity, and account counts.

        Args:
            wallet_text: Wallet address.

        Returns:
            A completed wallet scan report.

        Raises:
            ValueError: If the address is invalid.
        """

        wallet = self.rpc.parse_address(wallet_text)
        report = self.new_report("wallet", wallet_text)

        LOGGER.info("Reading wallet balance, activity, and token accounts")
        with ThreadPoolExecutor(max_workers=4) as pool:
            balance_future = pool.submit(self.rpc.get_balance_sol, wallet)
            signatures_future = pool.submit(
                self.rpc.get_signatures, wallet, 10
            )
            spl_future = pool.submit(
                self._get_accounts_for_program, wallet, SPL_TOKEN_PROGRAM_ID
            )
            token_2022_future = pool.submit(
                self._get_accounts_for_program, wallet, TOKEN_2022_PROGRAM_ID
            )
            sol_balance = balance_future.result()
            signatures = signatures_future.result()
            spl_accounts, spl_error = spl_future.result()
            token_2022_accounts, token_2022_error = token_2022_future.result()

        report.summary["sol_balance"] = sol_balance
        report.summary["recent_signature_count"] = len(signatures)
        report.summary["token_accounts"] = self._token_account_summary(
            spl_accounts,
            spl_error,
            token_2022_accounts,
            token_2022_error,
        )

        if sol_balance == 0:
            report.findings.append(
                Finding(
                    "medium",
                    "Zero SOL balance",
                    "The wallet has no SOL at scan time.",
                    "on-chain RPC",
                )
            )
        if len(signatures) == 0:
            report.findings.append(
                Finding(
                    "low",
                    "No recent signatures",
                    "The RPC returned no recent signatures for this wallet.",
                    "on-chain RPC",
                )
            )
        if spl_error:
            report.findings.append(
                Finding(
                    "medium",
                    "SPL token inventory incomplete",
                    spl_error,
                    "on-chain RPC",
                )
            )
        if token_2022_error:
            report.findings.append(
                Finding(
                    "medium",
                    "Token-2022 inventory incomplete",
                    token_2022_error,
                    "on-chain RPC",
                )
            )
        return report

    def _token_account_summary(
        self,
        spl_accounts,
        spl_error,
        token_2022_accounts,
        token_2022_error,
    ) -> dict[str, Any]:
        spl_count = len(spl_accounts) if spl_accounts is not None else None
        token_2022_count = (
            len(token_2022_accounts)
            if token_2022_accounts is not None
            else None
        )
        counted = [
            count
            for count in (spl_count, token_2022_count)
            if count is not None
        ]
        summary = {
            "spl_token_account_count": spl_count,
            "token_2022_account_count": token_2022_count,
            "total_account_count": sum(counted) if counted else None,
            "note": "This is a shallow inventory. No recursive wallet graph "
            "nonsense here.",
        }
        if spl_error:
            summary["spl_token_error"] = spl_error
        if token_2022_error:
            summary["token_2022_error"] = token_2022_error
        return summary

    def _get_accounts_for_program(
        self, wallet, program_id
    ) -> tuple[list[Any] | None, str | None]:
        """Fetch a wallet's token accounts for one token program."""

        try:
            return self.rpc.get_token_accounts_by_owner(
                wallet, program_id
            ), None
        except Exception as error:
            return None, str(error)
